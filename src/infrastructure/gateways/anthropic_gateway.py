"""Gateway to Anthropic's Messages API behind the router's OpenAI-shaped interface (ADR 0092).

This module has two sections:

1. ``AnthropicGateway``: the public interface, shaped like ``OpenAICompatibleGateway`` so the
   routing gateway, vcr-auto, Key Failover, Token Usage and Prompt Log need no change.
2. Upstream transport: the key pool, Key Failover and the Anthropic SSE event stream.
   Upstream calls always stream; non-stream replies are assembled by the router.

Translation lives in sibling modules, each with its own reason to change:
``anthropic_request_translation`` (student requests into a Messages request),
``anthropic_reply_translation`` (Anthropic events into Responses and chat replies and streams) and
``anthropic_thinking_envelope`` (the thinking round trip, ADR 0093).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from src.domain.entities.chat import ChatCompletionRequest
from src.domain.errors import (
    DecisionNotSupportedError,
    EmbeddingsNotSupportedError,
    ImageGenerationNotSupportedError,
    ServiceUnavailableError,
    SpeechTranscriptionNotSupportedError,
    TtsNotSupportedError,
    UpstreamServiceError,
    UpstreamTransportError,
    extract_upstream_error_text,
)
from src.domain.extra_usage import is_anthropic_credit_exhaustion
from src.infrastructure.config import ProviderSettings, resolve_provider_api_keys
from src.infrastructure.gateways.anthropic_reply_translation import (
    ChatStream,
    ReplyStream,
    ResponsesStream,
    assemble_message,
    chat_reply_from_message,
    encode_chat_chunk,
    encode_responses_event,
    responses_reply_from_message,
)
from src.infrastructure.gateways.anthropic_request_translation import (
    messages_request_from_chat,
    messages_request_from_responses,
)
from src.infrastructure.gateways.slot_policy import wait_for_pool_slot
from src.infrastructure.gateways.upstream_key_pool import NoSelectableUpstreamKeyError, UpstreamKeyPool

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2026-10-21"
# Lets every request ask Anthropic to drop an invalid thinking block instead of failing (ADR 0093).
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
_MESSAGES_PATH = "/messages"
_MODELS_PATH = "/models"
_MODELS_PARAMS = {"lifecycle": "active", "limit": "1000"}
DEFAULT_CREDIT_EXHAUSTION_MESSAGE = "Anthropic credit is exhausted or a spend limit was reached"
CONTENT_REFUSAL_MESSAGE = "Claude 拒絕回應這個請求，請換個說法再試"


# ---------------------------------------------------------------------------
# 1. Public interface
# ---------------------------------------------------------------------------


class AnthropicGateway:
    def __init__(
        self,
        provider: ProviderSettings,
        timeout: float = 900.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.provider = provider
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._pool = _create_pool(provider)

    async def startup(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, transport=self._transport)

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> dict[str, Any]:
        # No upstream call, so a probe spends nothing. A missing key must not fail the router's
        # /health either: the OpenAI-compatible gateway treats a 401 from upstream as healthy too.
        return {"ok": True, "pool": self.pool_status()}

    async def models(self) -> dict[str, Any]:
        """Active models in one call; the Upstream Model Catalog lists them under All Models."""
        client, pool, base_url = await self._upstream()
        # A listing takes no concurrency slot; any key that is not quarantined will do.
        index = next((i for i in range(pool.key_count) if not pool.is_quarantined(i)), 0)
        headers = {
            **self.provider.extra_headers,
            "x-api-key": pool.key_at(index),
            "anthropic-version": ANTHROPIC_VERSION,
        }
        try:
            response = await client.get(
                f"{base_url}{_MODELS_PATH}",
                headers=headers,
                params=_MODELS_PARAMS,
            )
        except httpx.RequestError as exc:
            raise UpstreamTransportError(f"{self.provider.name} unavailable: {exc}") from exc
        if response.status_code >= 400:
            raise UpstreamServiceError(
                status_code=response.status_code,
                backend=self.provider.name,
                body=_json_or_text(response.text),
            )
        listed = response.json()
        return {
            "data": [
                {"id": item["id"], "name": item.get("display_name") or item["id"]}
                for item in ((listed.get("data") if isinstance(listed, dict) else None) or [])
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
            ]
        }

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = messages_request_from_responses(body)
        message = await assemble_message(self._message_events(payload))
        return responses_reply_from_message(message, model=str(body.get("model") or message.model))

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        payload = messages_request_from_responses(body)
        stream = ResponsesStream(model=str(body.get("model") or ""))
        async for out in self._drive_stream(payload, stream):
            yield encode_responses_event(out)

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        payload = messages_request_from_chat(req)
        message = await assemble_message(self._message_events(payload))
        return chat_reply_from_message(message, model=req.model or message.model)

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        payload = messages_request_from_chat(req)
        stream = ChatStream(model=req.model)
        async for chunk in self._drive_stream(payload, stream):
            yield encode_chat_chunk(chunk)
        yield b"data: [DONE]\n\n"

    async def images_create(self, body: dict[str, Any]) -> dict[str, Any]:
        raise ImageGenerationNotSupportedError()

    async def images_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        raise ImageGenerationNotSupportedError()
        yield b""  # pragma: no cover

    async def images_models(self) -> dict[str, Any]:
        return {"data": []}

    async def embeddings_create(self, body: dict[str, Any]) -> dict[str, Any]:
        raise EmbeddingsNotSupportedError("Claude 不支援 /v1/embeddings")

    async def embeddings_models(self) -> dict[str, Any]:
        return {"data": []}

    async def audio_speech_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        raise TtsNotSupportedError()
        yield b""  # pragma: no cover

    async def audio_transcriptions_create(
        self,
        fields: dict[str, Any],
        file: tuple[str, bytes, str | None],
    ) -> dict[str, Any]:
        raise SpeechTranscriptionNotSupportedError()

    async def audio_transcriptions_create_stream(
        self,
        fields: dict[str, Any],
        file: tuple[str, bytes, str | None],
    ) -> AsyncGenerator[bytes, None]:
        raise SpeechTranscriptionNotSupportedError()
        yield b""  # pragma: no cover

    async def decisions_create(self, body: dict[str, Any]) -> dict[str, Any]:
        raise DecisionNotSupportedError("Claude 不支援 /v1/decisions")

    # Optional methods the routing gateway and Portal call through getattr.
    # The money overlays (attach_*) are deliberately absent: Anthropic has no balance API.

    def pool_status(self, *, limited_only: bool = False) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        if limited_only and self.provider.max_concurrent_per_key <= 0:
            return None
        raw = self._pool.status()
        label_prefix = self.provider.name.upper()
        return {
            "key_count": raw["key_count"],
            "max_concurrent_per_key": raw["max_concurrent_per_key"],
            "capacity": raw["capacity"],
            "in_flight_total": raw["in_flight_total"],
            "waiting": raw["waiting"],
            "busy_total": raw["busy_total"],
            "keys": [
                {
                    "index": item["index"],
                    "label": f"{label_prefix} {int(item['index']) + 1}",
                    "in_flight": item["in_flight"],
                    "cap": item["cap"],
                    "quarantined": item.get("quarantined", False),
                    "quarantine_remaining_sec": item.get("quarantine_remaining_sec"),
                }
                for item in raw["keys"]
            ],
        }

    async def release_key_quarantine(self, index: int) -> None:
        pool = self._require_pool_for_admin()
        if not (0 <= index < pool.key_count):
            raise IndexError(f"key index {index} out of range")
        await pool.release_quarantine(index)

    def is_key_quarantined(self, index: int) -> bool:
        return self._require_pool_for_admin().is_quarantined(index)

    def _require_pool_for_admin(self) -> UpstreamKeyPool:
        if self._pool is None:
            raise KeyError(f"provider「{self.provider.name}」has no upstream key pool")
        return self._pool

    # -----------------------------------------------------------------------
    # 2. Upstream transport: key pool, Key Failover, Anthropic SSE events
    # -----------------------------------------------------------------------

    async def _upstream(self) -> tuple[httpx.AsyncClient, UpstreamKeyPool, str]:
        """The client, the key pool and the base URL, or ServiceUnavailableError when one is missing."""
        await self.startup()
        assert self._client is not None
        if not self.provider.base_url:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: missing base_url")
        if self._pool is None:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: no API key configured")
        return self._client, self._pool, self.provider.base_url.rstrip("/")

    async def _drive_stream(self, payload: dict[str, Any], stream: ReplyStream) -> AsyncGenerator[dict[str, Any], None]:
        """Feed one Messages stream through ``stream`` and yield what it emits, ending with ``finish``.

        An error before ``stream`` has emitted anything raises, so the router's error handling and
        vcr-auto still apply. Mid-stream (a refusal stop, or an in-stream error event) the same reply
        ends with a Readable Upstream Error, as the router's own stream error handling would.
        """
        try:
            async for event in self._message_events(payload):
                for out in stream.feed(event):
                    yield out
        except (UpstreamServiceError, ServiceUnavailableError) as exc:
            if not stream.started:
                raise
            message = exc.user_facing_message() if isinstance(exc, UpstreamServiceError) else exc.message
            logger.warning(
                "anthropic_stream_ended_by_error provider=%s status=%s message=%s",
                self.provider.name,
                exc.status_code,
                message,
            )
            for out in stream.fail(message):
                yield out
        for out in stream.finish():
            yield out

    async def _message_events(self, payload: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        """Stream one Messages request and yield its parsed SSE events.

        Errors before the first event raise without yielding, so vcr-auto can still move on.
        """
        client, pool, base_url = await self._upstream()
        url = f"{base_url}{_MESSAGES_PATH}"
        tried: set[int] = set()
        last_error: UpstreamServiceError | None = None
        while True:
            if pool.all_quarantined():
                raise last_error or self._exhausted_keys_error(pool)
            index: int | None = None
            failover = False
            try:
                try:
                    index = await pool.acquire(exclude=frozenset(tried), wait=wait_for_pool_slot.get())
                except NoSelectableUpstreamKeyError as exc:
                    raise (last_error or self._exhausted_keys_error(pool)) from exc
                try:
                    async with client.stream(
                        "POST", url, headers=self._headers(pool.key_at(index)), json=payload
                    ) as response:
                        if response.status_code >= 400:
                            text = (await response.aread()).decode("utf-8", errors="replace")
                            if not is_anthropic_credit_exhaustion(response.status_code, text):
                                raise UpstreamServiceError(
                                    status_code=response.status_code,
                                    backend=self.provider.name,
                                    body=_json_or_text(text),
                                )
                            last_error = self._quarantine_exhausted_key(pool, index, text)
                            tried.add(index)
                            failover = True
                            logger.info(
                                "key_failover provider=%s failed_index=%s tried=%s",
                                self.provider.name,
                                index,
                                sorted(tried),
                            )
                        else:
                            if tried:
                                logger.info(
                                    "key_failover_success provider=%s index=%s after_tried=%s",
                                    self.provider.name,
                                    index,
                                    sorted(tried),
                                )
                            async for event in _sse_events(response):
                                if event.get("type") == "error":
                                    raise self._stream_error(event)
                                if _stop_reason(event) == "refusal":
                                    raise self._content_refusal_error()
                                _log_input_transformations(event, payload.get("model"))
                                yield event
                            return
                except httpx.RequestError as exc:
                    raise UpstreamTransportError(f"{self.provider.name} unavailable: {exc}") from exc
            finally:
                await _release_pool_slot(pool, index)
            if not failover:
                return

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "accept": "text/event-stream",
            **self.provider.extra_headers,
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "anthropic-beta": THINKING_BINDING_BETA,
        }

    def _exhausted_keys_error(self, pool: UpstreamKeyPool) -> UpstreamServiceError:
        return self._credit_exhaustion_error(pool.last_extra_usage_message or DEFAULT_CREDIT_EXHAUSTION_MESSAGE)

    def _quarantine_exhausted_key(self, pool: UpstreamKeyPool, index: int, text: str) -> UpstreamServiceError:
        message = extract_upstream_error_text(text) or DEFAULT_CREDIT_EXHAUSTION_MESSAGE
        pool.quarantine(index, message)
        return self._credit_exhaustion_error(message, upstream=_json_or_text(text))

    def _credit_exhaustion_error(self, message: str, *, upstream: Any = None) -> UpstreamServiceError:
        # Anthropic's exhaustion bodies carry no OpenRouter or Ollama marker, so the router's
        # provider-agnostic checks (vcr-auto, operator alerts) would miss them. Re-shape them as
        # a 402 Credit Exhaustion; the student still reads Anthropic's own message.
        body: dict[str, Any] = {"error": {"type": "payment_required", "message": message}}
        if upstream is not None:
            body["upstream"] = upstream
        return UpstreamServiceError(status_code=402, backend=self.provider.name, body=body)

    def _content_refusal_error(self) -> UpstreamServiceError:
        # A refusal is Claude's answer, not a failing key or Model ID: no quarantine, vcr-auto stops.
        return UpstreamServiceError(
            status_code=400,
            backend=self.provider.name,
            body={"error": {"type": "refusal", "message": CONTENT_REFUSAL_MESSAGE}},
        )

    def _stream_error(self, event: dict[str, Any]) -> UpstreamServiceError:
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        status = _STREAM_ERROR_STATUS.get(str(error.get("type")), 502)
        return UpstreamServiceError(status_code=status, backend=self.provider.name, body=event)


def _stop_reason(event: dict[str, Any]) -> str | None:
    if event.get("type") != "message_delta":
        return None
    delta = event.get("delta")
    return str(delta["stop_reason"]) if isinstance(delta, dict) and delta.get("stop_reason") else None


def _log_input_transformations(event: dict[str, Any], model: Any) -> None:
    """Log each change Anthropic made to the input (a dropped thinking block and why); never stored.

    ``message_start`` carries the array on its message; after a server-side fallback the final
    ``message_delta`` carries it again with the serving model's entries.
    """
    kind = event.get("type")
    if kind == "message_start":
        holder = event.get("message")
    elif kind == "message_delta":
        holder = event
    else:
        return
    entries = holder.get("input_transformations") if isinstance(holder, dict) else None
    if not isinstance(entries, list):
        return
    for entry in entries:
        reason = entry.get("reason") if isinstance(entry, dict) else None
        logger.warning(
            "anthropic_input_transformation model=%s reason=%s entry=%s",
            model,
            reason,
            json.dumps(entry, ensure_ascii=False)[:500],
        )


_STREAM_ERROR_STATUS = {
    "overloaded_error": 529,
    "rate_limit_error": 429,
    "api_error": 500,
    "invalid_request_error": 400,
}


def _create_pool(provider: ProviderSettings) -> UpstreamKeyPool | None:
    keys = resolve_provider_api_keys(provider)
    if not keys:
        return None
    return UpstreamKeyPool(
        keys,
        max_concurrent_per_key=provider.max_concurrent_per_key,
        queue_timeout_sec=provider.queue_timeout_sec,
        acquire_delay_ms=provider.acquire_delay_ms,
        quarantine_ttl_sec=provider.quarantine_ttl_sec,
    )


async def _release_pool_slot(pool: UpstreamKeyPool, index: int | None) -> None:
    """Release without masking the caller's primary exception (cancellation still propagates)."""
    if index is None:
        return
    try:
        await pool.release(index)
    except asyncio.CancelledError:
        raise
    except Exception:
        return


async def _sse_events(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        if line == "" and data_lines:
            raw = "\n".join(data_lines)
            data_lines = []
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event
    if data_lines:
        try:
            event = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return
        if isinstance(event, dict):
            yield event


def _json_or_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
