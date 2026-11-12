"""Gateway to Anthropic's Messages API behind the router's OpenAI-shaped interface (ADR 0092).

The module has four sections:

1. ``AnthropicGateway``: the public interface, shaped like ``OpenAICompatibleGateway`` so the
   routing gateway, vcr-auto, Key Failover, Token Usage and Prompt Log need no change.
2. Upstream transport: the key pool, Key Failover and the Anthropic SSE event stream.
   Upstream calls always stream; non-stream replies are assembled by the router.
3. Request translation: student requests (Responses, later chat) into a Messages request,
   deterministic so the same history always produces the same bytes (ADR 0093).
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
        raise self._refusal("Claude 目前只支援非串流的 /v1/responses")
        yield b""  # pragma: no cover - makes this an async generator

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
    n = body.get("n")
    if isinstance(n, int) and not isinstance(n, bool) and n > 1:
        raise _translation_refusal("Claude 一次只能產生一個回答，不支援 n > 1")
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
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    tools = _anthropic_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = _anthropic_tool_choice(body.get("tool_choice"), body.get("parallel_tool_calls"))
    output_format = _structured_output_format(body.get("text"))
    if output_format:
        # output_config also carries effort; merge so neither setting overwrites the other.
        payload.setdefault("output_config", {})["format"] = output_format
    return payload


def _structured_output_format(text: Any) -> dict[str, Any] | None:
    """A Responses JSON-schema text format as Anthropic structured outputs; other formats send nothing."""
    fmt = text.get("format") if isinstance(text, dict) else None
    if not isinstance(fmt, dict) or fmt.get("type") != "json_schema" or not isinstance(fmt.get("schema"), dict):
        return None
    return {"type": "json_schema", "schema": fmt["schema"]}


def _anthropic_tool_choice(tool_choice: Any, parallel_tool_calls: Any) -> dict[str, Any]:
    # A forced choice (`required` or a named tool) becomes auto: Opus 5.5 and Fable 5.2 reject it (ADR 0092).
    if tool_choice == "none" or (isinstance(tool_choice, dict) and tool_choice.get("type") == "none"):
        return {"type": "none"}
    choice: dict[str, Any] = {"type": "auto"}
    if parallel_tool_calls is False:
        choice["disable_parallel_tool_use"] = True
    return choice


def _anthropic_tools(raw_tools: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in raw_tools if isinstance(raw_tools, list) else []:
        if not isinstance(tool, dict) or tool.get("type") != "function" or not tool.get("name"):
            kind = tool.get("type") if isinstance(tool, dict) else type(tool).__name__
            # Server tools (web search, code execution) are out of scope; drop them, keep the rest.
            logger.info("anthropic_tool_dropped type=%s", kind)
            continue
        translated: dict[str, Any] = {"name": str(tool["name"])}
        if tool.get("description"):
            translated["description"] = str(tool["description"])
        parameters = tool.get("parameters")
        translated["input_schema"] = parameters if isinstance(parameters, dict) else {"type": "object"}
        tools.append(translated)
    return tools


def _responses_item_to_blocks(item: Any) -> tuple[str, list[dict[str, Any]]]:
    item_type = item.get("type", "message") if isinstance(item, dict) else type(item).__name__
    if item_type == "function_call":
        return "assistant", [_tool_use_block(item)]
    if item_type == "function_call_output":
        return "user", [_tool_result_block(item)]
    if item_type != "message":
        raise _translation_refusal(f"Claude 目前不支援輸入項目「{item_type}」")
    role = item.get("role")
    if role in ("system", "developer"):
        role = "system"
    elif role not in ("user", "assistant"):
        raise _translation_refusal(f"Claude 不支援角色「{role}」")
    blocks = _content_blocks(item.get("content"))
    if role == "system" and any(block["type"] != "text" for block in blocks):
        raise _translation_refusal("Claude 的系統指示只能是文字")
    return role, blocks


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [_text_block(content)]
    blocks: list[dict[str, Any]] = []
    for part in content or []:
        part_type = part.get("type") if isinstance(part, dict) else None
        if part_type in ("input_text", "output_text", "text"):
            blocks.append(_text_block(str(part.get("text") or "")))
        elif part_type in ("input_image", "image_url"):
            blocks.append(_image_block(part))
        elif part_type in ("input_file", "file"):
            raise _translation_refusal("Claude 目前不支援檔案附件，請改貼文字或圖片")
        elif part_type in ("input_audio", "audio"):
            raise _translation_refusal("Claude 不支援語音輸入，請改用文字")
        else:
            raise _translation_refusal(f"Claude 目前不支援內容「{part_type}」")
    return blocks


def _image_block(part: dict[str, Any]) -> dict[str, Any]:
    url = part.get("image_url")
    if isinstance(url, dict):  # chat-style {"image_url": {"url": ...}}
        url = url.get("url")
    if not isinstance(url, str) or not url:
        # A file_id points into OpenAI's file store, which Anthropic cannot read.
        raise _translation_refusal("Claude 只能接收網址或內嵌的圖片，不支援以檔案 ID 傳圖")
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media_type = header[len("data:") :].split(";")[0] or "image/png"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _tool_use_block(item: dict[str, Any]) -> dict[str, Any]:
    # The call id is the original Anthropic tool-use id, so it goes back unchanged.
    try:
        tool_input = json.loads(item.get("arguments") or "{}")
    except (TypeError, json.JSONDecodeError):
        tool_input = {}
    return {
        "type": "tool_use",
        "id": str(item.get("call_id") or ""),
        "name": str(item.get("name") or ""),
        "input": tool_input if isinstance(tool_input, dict) else {},
    }


def _tool_result_block(item: dict[str, Any]) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": str(item.get("call_id") or "")}
    output = item.get("output")
    if isinstance(output, list):
        content = [b for b in _content_blocks(output) if b["type"] != "text" or b["text"]]
        if content:
            block["content"] = content
    elif output:
        block["content"] = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return block


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
    # Tool input arrives as JSON text in pieces; it is parsed into the block's `input` on block stop,
    # so `content` always holds plain Anthropic content blocks.
    _partial_json: dict[int, str] = field(default_factory=dict, repr=False)

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
            if delta.get("type") == "text_delta":
                block = self._block_at(event)
                block["text"] = str(block.get("text") or "") + str(delta.get("text") or "")
            elif delta.get("type") == "input_json_delta":
                index = _event_index(event)
                self._partial_json[index] = self._partial_json.get(index, "") + str(delta.get("partial_json") or "")
        elif kind == "content_block_stop":
            index = _event_index(event)
            raw = self._partial_json.pop(index, "")
            if raw:
                block = self._block_at(event)
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {}
                block["input"] = parsed if isinstance(parsed, dict) else {}
        elif kind == "message_delta":
            delta = event.get("delta") or {}
            if delta.get("stop_reason"):
                self.stop_reason = str(delta["stop_reason"])
            self._merge_usage(event.get("usage"))

    def text(self) -> str:
        return "".join(str(block.get("text") or "") for block in self.content if block.get("type") == "text")

    def tool_uses(self) -> list[dict[str, Any]]:
        return [block for block in self.content if block.get("type") == "tool_use"]

    def _block_at(self, event: dict[str, Any]) -> dict[str, Any]:
        index = _event_index(event)
        while len(self.content) <= index:
            self.content.append({})
        return self.content[index]

    def _merge_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key, value in usage.items():
            if isinstance(value, int) and not isinstance(value, bool):
                self.usage[key] = value


def _event_index(event: dict[str, Any]) -> int:
    return int(event.get("index") or 0)


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


def function_call_item_from_tool_use(block: dict[str, Any]) -> dict[str, Any]:
    """A Responses function_call for one Anthropic tool_use block; the tool-use id is the call id."""
    call_id = str(block.get("id") or "")
    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    return {
        "type": "function_call",
        "id": f"fc_{call_id}",
        "call_id": call_id,
        "name": str(block.get("name") or ""),
        "arguments": json.dumps(tool_input, ensure_ascii=False),
        "status": "completed",
    }


def responses_output_from_message(message: AnthropicMessage) -> list[dict[str, Any]]:
    """Output items: one assistant message with the text, then one function_call per tool use."""
    output: list[dict[str, Any]] = []
    tool_uses = message.tool_uses()
    text = message.text()
    if text or not tool_uses:
        output.append(
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    output.extend(function_call_item_from_tool_use(block) for block in tool_uses)
    return output


def responses_reply_from_message(message: AnthropicMessage, *, model: str) -> dict[str, Any]:
    incomplete = message.stop_reason == "max_tokens"
    return {
        "id": f"resp_{message.id or uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "incomplete" if incomplete else "completed",
        "incomplete_details": {"reason": "max_output_tokens"} if incomplete else None,
        "model": model,
        "output": responses_output_from_message(message),
        "usage": openai_usage_from_anthropic(message.usage),
    }
