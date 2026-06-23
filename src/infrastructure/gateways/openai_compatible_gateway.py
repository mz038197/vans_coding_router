from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator

import httpx

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.domain.errors import ImageGenerationNotSupportedError, ServiceUnavailableError, UpstreamServiceError
from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.copilot_compat import (
    OllamaThinkingCache,
    derive_ollama_native_base,
    is_ollama_provider,
    strip_ollama_cloud_inference_suffix,
    normalize_chat_completions_response,
    normalize_chat_completions_sse,
    sanitize_responses_request,
)

_ollama_thinking_cache = OllamaThinkingCache()
_IMAGE_API_PROVIDERS = frozenset({"openrouter"})


class OpenAICompatibleGateway:
    def __init__(self, provider: ProviderSettings, timeout: float = 900.0):
        self.provider = provider
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> dict[str, Any]:
        try:
            response = await self._request("GET", "/models")
            return {"ok": response.status_code < 500, "status_code": response.status_code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def models(self) -> dict[str, Any]:
        response = await self._request("GET", "/models")
        return self._json_or_error(response)

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        response = await self._request("POST", "/chat/completions", json=_chat_payload(req, stream=False))
        return normalize_chat_completions_response(self._json_or_error(response))

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        payload = _chat_payload(req, stream=True)
        payload.setdefault("stream_options", {"include_usage": True})
        upstream = self._stream("POST", "/chat/completions", json=payload)
        async for chunk in normalize_chat_completions_sse(upstream):
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
        async for chunk in self._stream("POST", "/responses", json=payload):
            yield chunk

    async def images_create(self, body: dict[str, Any]) -> dict[str, Any]:
        self._assert_image_provider()
        response = await self._request("POST", "/images", json=body)
        return self._json_or_error(response)

    async def images_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        self._assert_image_provider()
        payload = dict(body)
        payload["stream"] = True
        async for chunk in self._stream("POST", "/images", json=payload):
            yield chunk

    async def images_models(self) -> dict[str, Any]:
        self._assert_image_provider()
        response = await self._request("GET", "/images/models")
        return self._json_or_error(response)

    def _assert_image_provider(self) -> None:
        if self.provider.name not in _IMAGE_API_PROVIDERS:
            raise ImageGenerationNotSupportedError(
                f"provider「{self.provider.name}」不支援 /v1/images，請使用 openrouter@..."
            )

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        await self.startup()
        assert self._client is not None
        try:
            return await self._client.request(
                method,
                f"{self.provider.base_url}{path}",
                headers=self._headers(),
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: {exc}") from exc

    async def _stream(self, method: str, path: str, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        await self.startup()
        assert self._client is not None
        try:
            async with self._client.stream(
                method,
                f"{self.provider.base_url}{path}",
                headers=self._headers(),
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

    def _json_or_error(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = response.text
        if response.status_code >= 400:
            raise UpstreamServiceError(status_code=response.status_code, backend=self.provider.name, body=body)
        return body if isinstance(body, dict) else {"data": body}

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", **self.provider.extra_headers}
        key = self.provider.api_key or (os.getenv(self.provider.api_key_env) if self.provider.api_key_env else "")
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
