from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from typing import Any, AsyncGenerator

import httpx

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.domain.errors import (
    ImageGenerationNotSupportedError,
    ServiceUnavailableError,
    TtsNotSupportedError,
    UpstreamServiceError,
)
from src.infrastructure.config import (
    CAPABILITY_AUDIO_SPEECH,
    ProviderSettings,
    providers_with_capability,
    resolve_provider_api_keys,
)
from src.infrastructure.gateways.copilot_compat import (
    OllamaThinkingCache,
    derive_ollama_native_base,
    is_ollama_provider,
    strip_ollama_cloud_inference_suffix,
    normalize_chat_completions_response,
    normalize_chat_completions_sse,
    sanitize_responses_request,
)
from src.infrastructure.gateways.upstream_key_pool import UpstreamKeyPool

_ollama_thinking_cache = OllamaThinkingCache()
_IMAGE_API_PROVIDERS = frozenset({"openrouter"})


class OpenAICompatibleGateway:
    def __init__(self, provider: ProviderSettings, timeout: float = 900.0):
        self.provider = provider
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        # Build once at construction so concurrent requests share one pool.
        self._pool = self._create_pool()

    def _create_pool(self) -> UpstreamKeyPool | None:
        keys = resolve_provider_api_keys(self.provider)
        if not keys:
            return None
        return UpstreamKeyPool(
            keys,
            max_concurrent_per_key=self.provider.max_concurrent_per_key,
            queue_timeout_sec=self.provider.queue_timeout_sec,
            acquire_delay_ms=self.provider.acquire_delay_ms,
        )

    def _ensure_pool(self) -> UpstreamKeyPool | None:
        return self._pool

    @staticmethod
    async def _release_pool_slot(pool: UpstreamKeyPool | None, index: int | None) -> None:
        """Release a pool slot without masking the caller's primary exception.

        ``UpstreamKeyPool.release`` is shielded for accounting safety. Any other
        unexpected failure here is swallowed so ``finally`` cannot replace the
        original request/stream error (cancellation is still propagated).
        """
        if pool is None or index is None:
            return
        try:
            await pool.release(index)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def startup(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def pool_status(self, *, limited_only: bool = False) -> dict[str, Any] | None:
        """Sanitized upstream key-pool snapshot, or None when unavailable / filtered."""
        if self._pool is None:
            return None
        if limited_only and self.provider.max_concurrent_per_key <= 0:
            return None
        raw = self._pool.status()
        label_prefix = self.provider.name.upper()
        keys = [
            {
                "index": item["index"],
                "label": f"{label_prefix} {int(item['index']) + 1}",
                "in_flight": item["in_flight"],
                "cap": item["cap"],
            }
            for item in raw["keys"]
        ]
        return {
            "key_count": raw["key_count"],
            "max_concurrent_per_key": raw["max_concurrent_per_key"],
            "capacity": raw["capacity"],
            "in_flight_total": raw["in_flight_total"],
            "waiting": raw["waiting"],
            "busy_total": raw["busy_total"],
            "keys": keys,
        }

    async def health(self) -> dict[str, Any]:
        pool = self.pool_status(limited_only=False)
        try:
            response = await self._request("GET", "/models", use_pool=False)
            return {
                "ok": response.status_code < 500,
                "status_code": response.status_code,
                "pool": pool,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "pool": pool}

    async def models(self) -> dict[str, Any]:
        response = await self._request("GET", "/models", use_pool=False)
        return self._json_or_error(response)

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        response = await self._request("POST", "/chat/completions", json=_chat_payload(req, stream=False))
        return normalize_chat_completions_response(self._json_or_error(response))

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        payload = _chat_payload(req, stream=True)
        payload.setdefault("stream_options", {"include_usage": True})
        upstream = self._stream("POST", "/chat/completions", json=payload)
        async with aclosing(normalize_chat_completions_sse(upstream)) as stream:
            async for chunk in stream:
                yield chunk

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = await self._prepare_responses_body(body)
        payload["stream"] = False
        response = await self._request("POST", "/responses", json=payload)
        return self._json_or_error(response)

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        payload = await self._prepare_responses_body(body)
        payload["stream"] = True
        payload.setdefault("stream_options", {"include_usage": True})
        async with aclosing(self._stream("POST", "/responses", json=payload)) as stream:
            async for chunk in stream:
                yield chunk

    async def images_create(self, body: dict[str, Any]) -> dict[str, Any]:
        self._assert_image_provider()
        response = await self._request("POST", "/images", json=body)
        return self._json_or_error(response)

    async def images_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        self._assert_image_provider()
        payload = dict(body)
        payload["stream"] = True
        async with aclosing(self._stream("POST", "/images", json=payload)) as stream:
            async for chunk in stream:
                yield chunk

    async def images_models(self) -> dict[str, Any]:
        self._assert_image_provider()
        response = await self._request("GET", "/images/models", use_pool=False)
        return self._json_or_error(response)

    async def audio_speech_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        self._assert_audio_speech_provider()
        async with aclosing(self._stream("POST", "/audio/speech", json=body)) as stream:
            async for chunk in stream:
                yield chunk

    def _assert_image_provider(self) -> None:
        if self.provider.name not in _IMAGE_API_PROVIDERS:
            raise ImageGenerationNotSupportedError(
                f"provider「{self.provider.name}」不支援 /v1/images，請使用 openrouter@..."
            )

    def _assert_audio_speech_provider(self) -> None:
        if CAPABILITY_AUDIO_SPEECH not in self.provider.capabilities:
            capable = providers_with_capability({self.provider.name: self.provider}, CAPABILITY_AUDIO_SPEECH)
            hint = f"{capable[0]}@..." if capable else "audio_speech provider"
            raise TtsNotSupportedError(
                f"provider「{self.provider.name}」不支援 /v1/audio/speech，請使用 {hint}"
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        use_pool: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        await self.startup()
        assert self._client is not None
        pool = self._ensure_pool() if use_pool else None
        index: int | None = None
        try:
            if pool is not None:
                index = await pool.acquire()
                headers = self._headers(api_key=pool.key_at(index))
            else:
                headers = self._headers()
            return await self._client.request(
                method,
                f"{self.provider.base_url}{path}",
                headers=headers,
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: {exc}") from exc
        finally:
            await self._release_pool_slot(pool, index)

    async def _stream(
        self,
        method: str,
        path: str,
        *,
        use_pool: bool = True,
        **kwargs: Any,
    ) -> AsyncGenerator[bytes, None]:
        await self.startup()
        assert self._client is not None
        pool = self._ensure_pool() if use_pool else None
        index: int | None = None
        try:
            if pool is not None:
                index = await pool.acquire()
                headers = self._headers(api_key=pool.key_at(index))
            else:
                headers = self._headers()
            try:
                async with self._client.stream(
                    method,
                    f"{self.provider.base_url}{path}",
                    headers=headers,
                    **kwargs,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise UpstreamServiceError(
                            status_code=response.status_code,
                            backend=self.provider.name,
                            body=body.decode("utf-8", errors="replace"),
                        )
                    async for chunk in response.aiter_bytes():
                        yield chunk
            except httpx.RequestError as exc:
                raise ServiceUnavailableError(f"{self.provider.name} unavailable: {exc}") from exc
        finally:
            await self._release_pool_slot(pool, index)

    def _json_or_error(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = response.text
        if response.status_code >= 400:
            raise UpstreamServiceError(status_code=response.status_code, backend=self.provider.name, body=body)
        return body if isinstance(body, dict) else {"data": body}

    def _headers(self, *, api_key: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json", **self.provider.extra_headers}
        key = api_key
        if key is None:
            pool = self._ensure_pool()
            key = pool.key_at(0) if pool is not None else ""
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def _prepare_responses_body(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = dict(body)
        if not is_ollama_provider(self.provider.name, self.provider.base_url):
            return payload

        model = payload.get("model")
        if not isinstance(model, str) or not model.strip():
            return payload

        native_base = derive_ollama_native_base(self.provider.base_url)
        if native_base is None:
            return payload

        await self.startup()
        assert self._client is not None
        show_model = strip_ollama_cloud_inference_suffix(model)
        # Probe uses first key without taking a concurrency slot (cached).
        supports_thinking = await _ollama_thinking_cache.supports_thinking(
            self._client,
            native_base,
            show_model,
            self._headers(),
        )
        return sanitize_responses_request(payload, supports_thinking)


def _chat_payload(req: ChatCompletionRequest, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": req.model,
        "messages": [_message_payload(message) for message in req.messages],
        "stream": stream,
    }
    optional = {
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "user": req.user,
        "stop": req.stop,
        "tools": req.tools,
        "tool_choice": req.tool_choice,
    }
    payload.update({key: value for key, value in optional.items() if value is not None})
    return payload


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    for key in ("tool_calls", "tool_call_id", "name"):
        value = getattr(message, key)
        if value is not None:
            payload[key] = value
    if message.tool_name is not None:
        payload["name"] = message.tool_name
    return payload
