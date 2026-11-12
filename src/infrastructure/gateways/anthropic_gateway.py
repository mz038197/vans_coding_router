"""Gateway to Anthropic's Messages API behind the router's OpenAI-shaped interface (ADR 0092).

The module has four sections:

1. ``AnthropicGateway``: the public interface, shaped like ``OpenAICompatibleGateway`` so the
   routing gateway, vcr-auto, Key Failover, Token Usage and Prompt Log need no change.
2. Upstream transport: the key pool, Key Failover and the Anthropic SSE event stream.
   Upstream calls always stream; non-stream replies are assembled by the router.
3. Request translation: student requests (Responses, later chat) into a Messages request.
4. Response translation: Anthropic events into the student's reply shape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import httpx

from src.domain.entities.chat import ChatCompletionRequest
from src.domain.errors import (
    ImageGenerationNotSupportedError,
    ServiceUnavailableError,
    SpeechTranscriptionNotSupportedError,
    TtsNotSupportedError,
    UpstreamServiceError,
    UpstreamTransportError,
    extract_upstream_error_text,
)
from src.domain.extra_usage import DEFAULT_EXTRA_USAGE_MESSAGE, is_key_failover_exhaustion
from src.infrastructure.config import ProviderSettings, resolve_provider_api_keys
from src.infrastructure.gateways.slot_policy import wait_for_pool_slot
from src.infrastructure.gateways.upstream_key_pool import NoSelectableUpstreamKeyError, UpstreamKeyPool

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2026-10-21"
DEFAULT_MAX_TOKENS = 32000
_MESSAGES_PATH = "/messages"


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
        return {"data": []}

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = messages_request_from_responses(body)
        message = await _assemble_message(self._message_events(payload))
        return responses_reply_from_message(message, model=str(body.get("model") or message.model))

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        payload = messages_request_from_responses(body)
        stream = ResponsesStream(model=str(body.get("model") or ""))
        async for event in self._message_events(payload):
            for out in stream.feed(event):
                yield _encode_responses_event(out)
        for out in stream.finish():
            yield _encode_responses_event(out)

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        raise self._refusal("Claude 目前不支援 /v1/chat/completions")

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        raise self._refusal("Claude 目前不支援 /v1/chat/completions")
        yield b""  # pragma: no cover

    async def images_create(self, body: dict[str, Any]) -> dict[str, Any]:
        raise ImageGenerationNotSupportedError()

    async def images_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        raise ImageGenerationNotSupportedError()
        yield b""  # pragma: no cover

    async def images_models(self) -> dict[str, Any]:
        return {"data": []}

    async def embeddings_create(self, body: dict[str, Any]) -> dict[str, Any]:
        raise self._refusal("Claude 不支援 /v1/embeddings")

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
        raise self._refusal("Claude 不支援 /v1/decisions")

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

    def _refusal(self, message: str) -> UpstreamServiceError:
        return UpstreamServiceError(
            status_code=400,
            backend=self.provider.name,
            body={"error": {"type": "invalid_request_error", "message": message}},
        )

    # -----------------------------------------------------------------------
    # 2. Upstream transport: key pool, Key Failover, Anthropic SSE events
    # -----------------------------------------------------------------------

    async def _message_events(self, payload: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        """Stream one Messages request and yield its parsed SSE events.

        Errors before the first event raise without yielding, so vcr-auto can still move on.
        """
        await self.startup()
        assert self._client is not None
        if not self.provider.base_url:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: missing base_url")
        pool = self._pool
        if pool is None:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: no API key configured")

        url = f"{self.provider.base_url.rstrip('/')}{_MESSAGES_PATH}"
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
                    async with self._client.stream(
                        "POST", url, headers=self._headers(pool.key_at(index)), json=payload
                    ) as response:
                        if response.status_code >= 400:
                            text = (await response.aread()).decode("utf-8", errors="replace")
                            if not is_key_failover_exhaustion(response.status_code, text):
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
        }

    def _exhausted_keys_error(self, pool: UpstreamKeyPool) -> UpstreamServiceError:
        body = {"error": pool.last_extra_usage_message or DEFAULT_EXTRA_USAGE_MESSAGE}
        return UpstreamServiceError(status_code=402, backend=self.provider.name, body=body)

    def _quarantine_exhausted_key(self, pool: UpstreamKeyPool, index: int, text: str) -> UpstreamServiceError:
        pool.quarantine(index, extract_upstream_error_text(text) or DEFAULT_EXTRA_USAGE_MESSAGE)
        return UpstreamServiceError(status_code=402, backend=self.provider.name, body=_json_or_text(text))

    def _stream_error(self, event: dict[str, Any]) -> UpstreamServiceError:
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        status = _STREAM_ERROR_STATUS.get(str(error.get("type")), 502)
        return UpstreamServiceError(status_code=status, backend=self.provider.name, body=event)


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


# ---------------------------------------------------------------------------
# 3. Request translation: student request -> Messages request
# ---------------------------------------------------------------------------


def messages_request_from_responses(body: dict[str, Any]) -> dict[str, Any]:
    """Build a Messages request from a Responses body.

    Fields are copied by allow-list, so sampling fields (temperature, top_p, top_k) and
    Copilot's own fields never reach Anthropic.
    """
    system_parts: list[str] = []
    if isinstance(body.get("instructions"), str) and body["instructions"]:
        system_parts.append(body["instructions"])

    messages: list[dict[str, Any]] = []
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        _append_message(messages, "user", [_text_block(raw_input)])
    elif isinstance(raw_input, list):
        for item in raw_input:
            role, blocks = _responses_item_to_blocks(item)
            if role == "system":
                system_parts.extend(block["text"] for block in blocks)
            else:
                _append_message(messages, role, blocks)

    payload: dict[str, Any] = {
        "model": body.get("model"),
        "messages": [_compact_message(message) for message in messages],
        "max_tokens": _max_tokens(body.get("max_output_tokens")),
        "stream": True,
        # Automatic prompt caching: Anthropic places the breakpoint on the last cacheable block.
        "cache_control": {"type": "ephemeral"},
        # The summary text becomes the Responses reasoning summary (Responses Reasoning Projection).
        "thinking": {"type": "adaptive", "display": "summarized"},
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    reasoning = body.get("reasoning")
    effort = _claude_effort(reasoning.get("effort") if isinstance(reasoning, dict) else None)
    if effort:
        payload["output_config"] = {"effort": effort}
    return payload


# Claude has no `minimal`; every other level keeps its name. Anything else sends no effort.
_CLAUDE_EFFORT = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}


def _claude_effort(value: Any) -> str | None:
    return _CLAUDE_EFFORT.get(value) if isinstance(value, str) else None


def _responses_item_to_blocks(item: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(item, dict) or item.get("type", "message") != "message":
        item_type = item.get("type") if isinstance(item, dict) else type(item).__name__
        raise _translation_refusal(f"Claude 目前不支援輸入項目「{item_type}」")
    role = item.get("role")
    if role in ("system", "developer"):
        role = "system"
    elif role not in ("user", "assistant"):
        raise _translation_refusal(f"Claude 不支援角色「{role}」")
    content = item.get("content")
    if isinstance(content, str):
        return role, [_text_block(content)]
    blocks: list[dict[str, Any]] = []
    for part in content or []:
        part_type = part.get("type") if isinstance(part, dict) else None
        if part_type in ("input_text", "output_text", "text"):
            blocks.append(_text_block(str(part.get("text") or "")))
        else:
            raise _translation_refusal(f"Claude 目前不支援內容「{part_type}」")
    return role, blocks


def _append_message(messages: list[dict[str, Any]], role: str, blocks: list[dict[str, Any]]) -> None:
    blocks = [block for block in blocks if block.get("type") != "text" or block.get("text")]
    if not blocks:
        return
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
    else:
        messages.append({"role": role, "content": list(blocks)})


def _compact_message(message: dict[str, Any]) -> dict[str, Any]:
    content = message["content"]
    if len(content) == 1 and content[0].get("type") == "text":
        return {"role": message["role"], "content": content[0]["text"]}
    return message


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _max_tokens(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_MAX_TOKENS


def _translation_refusal(message: str) -> UpstreamServiceError:
    return UpstreamServiceError(
        status_code=400,
        backend="anthropic",
        body={"error": {"type": "invalid_request_error", "message": message}},
    )


# ---------------------------------------------------------------------------
# 4. Response translation: Anthropic events -> student reply
# ---------------------------------------------------------------------------


@dataclass
class AnthropicMessage:
    """One assistant message assembled from Anthropic's stream events."""

    id: str = ""
    model: str = ""
    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    _id_suffix: str = ""

    def apply(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "message_start":
            message = event.get("message") or {}
            self.id = str(message.get("id") or "")
            self.model = str(message.get("model") or "")
            self._merge_usage(message.get("usage"))
        elif kind == "content_block_start":
            self._block_at(event).update(dict(event.get("content_block") or {}))
        elif kind == "content_block_delta":
            delta = event.get("delta") or {}
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                block = self._block_at(event)
                block["text"] = str(block.get("text") or "") + str(delta.get("text") or "")
            elif delta_type == "thinking_delta":
                block = self._block_at(event)
                block["thinking"] = str(block.get("thinking") or "") + str(delta.get("thinking") or "")
            elif delta_type == "signature_delta":
                block = self._block_at(event)
                block["signature"] = str(block.get("signature") or "") + str(delta.get("signature") or "")
        elif kind == "message_delta":
            delta = event.get("delta") or {}
            if delta.get("stop_reason"):
                self.stop_reason = str(delta["stop_reason"])
            self._merge_usage(event.get("usage"))

    def text(self) -> str:
        return "".join(str(block.get("text") or "") for block in self.content if block.get("type") == "text")

    def thinking_summaries(self) -> list[str]:
        """The summarized text of each thinking block, in order (``display: "summarized"``)."""
        return [str(block.get("thinking") or "") for block in self.content if block.get("type") == "thinking"]

    def item_id(self, prefix: str) -> str:
        """A stable output item id for this message, so streamed items match the completed reply."""
        if not self._id_suffix:
            self._id_suffix = self.id.removeprefix("msg_") or uuid.uuid4().hex
        return f"{prefix}_{self._id_suffix}"

    def _block_at(self, event: dict[str, Any]) -> dict[str, Any]:
        index = int(event.get("index") or 0)
        while len(self.content) <= index:
            self.content.append({})
        return self.content[index]

    def _merge_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key, value in usage.items():
            if isinstance(value, int) and not isinstance(value, bool):
                self.usage[key] = value


async def _assemble_message(events: AsyncGenerator[dict[str, Any], None]) -> AnthropicMessage:
    message = AnthropicMessage()
    async for event in events:
        message.apply(event)
    return message


def openai_usage_from_anthropic(usage: dict[str, int]) -> dict[str, Any]:
    """Map Anthropic usage to Responses usage; cache read and cache write count as input."""
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)
    input_tokens = usage.get("input_tokens", 0) + cache_read + cache_write
    output_tokens = usage.get("output_tokens", 0)
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cache_read},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def responses_reply_from_message(
    message: AnthropicMessage, *, model: str, created_at: int | None = None
) -> dict[str, Any]:
    """The completed Responses reply. Output items follow the order their first block arrived,
    which is also the order the stream announced them in."""
    output: list[dict[str, Any]] = []
    for kind in _output_kinds(message):
        if kind == "thinking":
            output.append(_responses_reasoning_item(message))
        elif kind == "text":
            output.append(_responses_message_item(message))
    if not output:
        output.append(_responses_message_item(message))
    incomplete = message.stop_reason == "max_tokens"
    return {
        "id": message.item_id("resp"),
        "object": "response",
        "created_at": created_at if created_at is not None else int(time.time()),
        "status": "incomplete" if incomplete else "completed",
        "incomplete_details": {"reason": "max_output_tokens"} if incomplete else None,
        "model": model,
        "output": output,
        "usage": openai_usage_from_anthropic(message.usage),
    }


class ResponsesStream:
    """Turns Anthropic stream events into Responses stream events, as they arrive.

    Thinking streams as reasoning summary events on one reasoning item (one summary part per
    thinking block); text streams as output text on one assistant message item. Items are
    finished at the end, from ``responses_reply_from_message``, so the done items and
    ``response.completed`` always equal the non-streaming reply.
    """

    def __init__(self, *, model: str):
        self.model = model
        self.message = AnthropicMessage()
        self._created_at = int(time.time())
        self._sequence = 0
        self._item_index: dict[str, int] = {}  # "thinking" | "text" -> output_index
        self._summary_index: dict[int, int] = {}  # Anthropic block index -> summary_index

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        self.message.apply(event)
        kind = event.get("type")
        if kind == "message_start":
            return [self._event("response.created", response=self._response_shell())]
        if kind == "content_block_start":
            return self._block_started(event)
        if kind == "content_block_delta":
            return self._block_delta(event)
        if kind == "content_block_stop":
            return self._block_stopped(event)
        return []

    def finish(self) -> list[dict[str, Any]]:
        reply = responses_reply_from_message(self.message, model=self.model, created_at=self._created_at)
        out: list[dict[str, Any]] = []
        for output_index, item in enumerate(reply["output"]):
            kind = "thinking" if item["type"] == "reasoning" else "text"
            if kind not in self._item_index:
                out.extend(self._open_item(kind))
            if kind == "text":
                part = item["content"][0]
                common = {"item_id": item["id"], "output_index": output_index, "content_index": 0}
                out.append(self._event("response.output_text.done", **common, text=part["text"]))
                out.append(self._event("response.content_part.done", **common, part=part))
            out.append(self._event("response.output_item.done", output_index=output_index, item=item))
        out.append(self._event("response.completed", response=reply))
        return out

    def _block_started(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        kind = (event.get("content_block") or {}).get("type")
        if kind == "thinking":
            out = self._open_item("thinking") if "thinking" not in self._item_index else []
            summary_index = len(self._summary_index)
            self._summary_index[_block_index(event)] = summary_index
            out.append(
                self._event(
                    "response.reasoning_summary_part.added",
                    **self._summary_common(summary_index),
                    part={"type": "summary_text", "text": ""},
                )
            )
            return out
        if kind == "text" and "text" not in self._item_index:
            return self._open_item("text")
        return []

    def _block_delta(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        delta = event.get("delta") or {}
        if delta.get("type") == "thinking_delta" and _block_index(event) in self._summary_index:
            return [
                self._event(
                    "response.reasoning_summary_text.delta",
                    **self._summary_common(self._summary_index[_block_index(event)]),
                    delta=str(delta.get("thinking") or ""),
                )
            ]
        if delta.get("type") == "text_delta" and "text" in self._item_index:
            return [
                self._event(
                    "response.output_text.delta",
                    item_id=self.message.item_id("msg"),
                    output_index=self._item_index["text"],
                    content_index=0,
                    delta=str(delta.get("text") or ""),
                )
            ]
        return []

    def _block_stopped(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        summary_index = self._summary_index.get(_block_index(event))
        if summary_index is None:
            return []
        text = str(self.message.content[_block_index(event)].get("thinking") or "")
        common = self._summary_common(summary_index)
        return [
            self._event("response.reasoning_summary_text.done", **common, text=text),
            self._event("response.reasoning_summary_part.done", **common, part={"type": "summary_text", "text": text}),
        ]

    def _open_item(self, kind: str) -> list[dict[str, Any]]:
        output_index = len(self._item_index)
        self._item_index[kind] = output_index
        if kind == "thinking":
            item = {"type": "reasoning", "id": self.message.item_id("rs"), "summary": []}
            return [self._event("response.output_item.added", output_index=output_index, item=item)]
        item_id = self.message.item_id("msg")
        item = {"type": "message", "id": item_id, "status": "in_progress", "role": "assistant", "content": []}
        return [
            self._event("response.output_item.added", output_index=output_index, item=item),
            self._event(
                "response.content_part.added",
                item_id=item_id,
                output_index=output_index,
                content_index=0,
                part={"type": "output_text", "text": "", "annotations": []},
            ),
        ]

    def _summary_common(self, summary_index: int) -> dict[str, Any]:
        return {
            "item_id": self.message.item_id("rs"),
            "output_index": self._item_index["thinking"],
            "summary_index": summary_index,
        }

    def _response_shell(self) -> dict[str, Any]:
        return {
            "id": self.message.item_id("resp"),
            "object": "response",
            "created_at": self._created_at,
            "status": "in_progress",
            "model": self.model,
            "output": [],
        }

    def _event(self, kind: str, **fields: Any) -> dict[str, Any]:
        event = {"type": kind, "sequence_number": self._sequence, **fields}
        self._sequence += 1
        return event


def _block_index(event: dict[str, Any]) -> int:
    return int(event.get("index") or 0)


def _encode_responses_event(event: dict[str, Any]) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def _output_kinds(message: AnthropicMessage) -> list[str]:
    """Block kinds in first-arrival order. All thinking blocks share one reasoning item
    (one summary part each); all text blocks share one assistant message item."""
    kinds: list[str] = []
    for block in message.content:
        kind = block.get("type")
        if kind in ("thinking", "text") and kind not in kinds:
            kinds.append(kind)
    return kinds


def _responses_reasoning_item(message: AnthropicMessage) -> dict[str, Any]:
    return {
        "type": "reasoning",
        "id": message.item_id("rs"),
        "summary": [{"type": "summary_text", "text": text} for text in message.thinking_summaries()],
    }


def _responses_message_item(message: AnthropicMessage) -> dict[str, Any]:
    return {
        "type": "message",
        "id": message.item_id("msg"),
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": message.text(), "annotations": []}],
    }
