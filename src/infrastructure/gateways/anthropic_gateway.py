"""Gateway to Anthropic's Messages API behind the router's OpenAI-shaped interface (ADR 0092).

The module has four sections:

1. ``AnthropicGateway``: the public interface, shaped like ``OpenAICompatibleGateway`` so the
   routing gateway, vcr-auto, Key Failover, Token Usage and Prompt Log need no change.
2. Upstream transport: the key pool, Key Failover and the Anthropic SSE event stream.
   Upstream calls always stream; non-stream replies are assembled by the router.
3. Request translation: student requests (Responses; chat restated as Responses) into a Messages request,
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

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
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
from src.infrastructure.gateways.anthropic_thinking_envelope import (
    AssistantRound,
    encode_thinking_envelope,
    replay_assistant_rounds,
)
from src.infrastructure.gateways.slot_policy import wait_for_pool_slot
from src.infrastructure.gateways.upstream_key_pool import NoSelectableUpstreamKeyError, UpstreamKeyPool

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2026-10-21"
# Lets every request ask Anthropic to drop an invalid thinking block instead of failing (ADR 0093).
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
DEFAULT_MAX_TOKENS = 32000
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
        await self.startup()
        assert self._client is not None
        if not self.provider.base_url:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: missing base_url")
        pool = self._pool
        if pool is None:
            raise ServiceUnavailableError(f"{self.provider.name} unavailable: no API key configured")
        # A listing takes no concurrency slot; any key that is not quarantined will do.
        index = next((i for i in range(pool.key_count) if not pool.is_quarantined(i)), 0)
        headers = {
            **self.provider.extra_headers,
            "x-api-key": pool.key_at(index),
            "anthropic-version": ANTHROPIC_VERSION,
        }
        try:
            response = await self._client.get(
                f"{self.provider.base_url.rstrip('/')}{_MODELS_PATH}",
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
        message = await _assemble_message(self._message_events(payload))
        return responses_reply_from_message(message, model=str(body.get("model") or message.model))

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        payload = messages_request_from_responses(body)
        stream = ResponsesStream(model=str(body.get("model") or ""))
        try:
            async for event in self._message_events(payload):
                for out in stream.feed(event):
                    yield _encode_responses_event(out)
        except (UpstreamServiceError, ServiceUnavailableError) as exc:
            if not stream.started:
                raise  # nothing sent yet: the router's error handling and vcr-auto still apply
            # Mid-stream (a refusal stop, or an in-stream error event): end this same response with
            # a Readable Upstream Error, as the router's own stream error handling would.
            message = exc.user_facing_message() if isinstance(exc, UpstreamServiceError) else exc.message
            logger.warning(
                "anthropic_stream_ended_by_error provider=%s status=%s message=%s",
                self.provider.name,
                exc.status_code,
                message,
            )
            for out in stream.fail(message):
                yield _encode_responses_event(out)
        for out in stream.finish():
            yield _encode_responses_event(out)

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        payload = messages_request_from_chat(req)
        message = await _assemble_message(self._message_events(payload))
        return chat_reply_from_message(message, model=req.model or message.model)

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        payload = messages_request_from_chat(req)
        stream = ChatStream(model=req.model)
        try:
            async for event in self._message_events(payload):
                for chunk in stream.feed(event):
                    yield _encode_chat_chunk(chunk)
        except (UpstreamServiceError, ServiceUnavailableError) as exc:
            if not stream.started:
                raise  # nothing sent yet: the router's error handling and vcr-auto still apply
            # Mid-stream (a refusal stop, or an in-stream error event): finish this same chat stream
            # with a Readable Upstream Error, as on Responses.
            message = exc.user_facing_message() if isinstance(exc, UpstreamServiceError) else exc.message
            logger.warning(
                "anthropic_stream_ended_by_error provider=%s status=%s message=%s",
                self.provider.name,
                exc.status_code,
                message,
            )
            for chunk in stream.fail(message):
                yield _encode_chat_chunk(chunk)
        for chunk in stream.finish():
            yield _encode_chat_chunk(chunk)
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
        raise _unsupported_request_error("Claude 一次只能產生一個回答，不支援 n > 1")
    system_parts: list[str] = []
    if isinstance(body.get("instructions"), str) and body["instructions"]:
        system_parts.append(body["instructions"])

    messages: list[dict[str, Any]] = []
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        _append_message(messages, "user", [_text_block(raw_input)])
    elif isinstance(raw_input, list):
        turns = _responses_turns(raw_input)
        system_parts.extend(block["text"] for role, blocks in turns if role == "system" for block in blocks)
        _append_replayed_turns(messages, [turn for turn in turns if turn[0] != "system"], model=str(body.get("model") or ""))

    payload: dict[str, Any] = {
        "model": body.get("model"),
        "messages": [_compact_message(message) for message in messages],
        "max_tokens": _max_tokens(body),
        "stream": True,
        # Automatic prompt caching: Anthropic places the breakpoint on the last cacheable block.
        "cache_control": {"type": "ephemeral"},
        # The summary text becomes the Responses reasoning summary (Responses Reasoning Projection).
        "thinking": thinking_config(),
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    tools = _anthropic_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = _anthropic_tool_choice(body.get("tool_choice"), body.get("parallel_tool_calls"))
    reasoning = body.get("reasoning")
    effort = _claude_effort(reasoning.get("effort") if isinstance(reasoning, dict) else None)
    if effort:
        payload.setdefault("output_config", {})["effort"] = effort
    output_format = _structured_output_format(body.get("text"))
    if output_format:
        payload.setdefault("output_config", {})["format"] = output_format
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


def thinking_config() -> dict[str, Any]:
    """Thinking for every Messages request: summarized adaptive thinking, and a thinking block that
    no longer matches its prefix is dropped rather than failing the request (ADR 0093)."""
    return {
        "type": "adaptive",
        "display": "summarized",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }


def _claude_effort(value: Any) -> str | None:
    return _CLAUDE_EFFORT.get(value) if isinstance(value, str) else None


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


def _responses_turns(items: list[Any]) -> list[tuple[str, Any]]:
    """Responses input items as turns: ``("system" | "user", blocks)`` or ``("assistant", AssistantRound)``.

    A round is one assistant reply: the run of assistant items (reasoning, message, function_call)
    between other turns. A reasoning item opens a new round, since every reply this router makes
    starts with one; its ``encrypted_content`` is the round's envelope and its summary is ignored.
    """
    turns: list[tuple[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "reasoning":
            turns.append(("assistant", AssistantRound(envelope=item.get("encrypted_content"))))
            continue
        role, blocks = _responses_item_to_blocks(item)
        if role == "assistant":
            if not turns or turns[-1][0] != "assistant":
                turns.append(("assistant", AssistantRound()))
            turns[-1][1].blocks.extend(blocks)
        else:
            turns.append((role, blocks))
    return turns


def _append_replayed_turns(messages: list[dict[str, Any]], turns: list[tuple[str, Any]], *, model: str) -> None:
    """Append user and assistant turns, rebuilding assistant rounds from their envelopes (ADR 0093).

    ``turns`` hold ``(role, blocks)`` for user turns and ``("assistant", AssistantRound)`` for rounds.
    """
    rounds = [value for role, value in turns if role == "assistant"]
    replayed = replay_assistant_rounds(rounds, model=model)
    if rounds:
        logger.info(
            "anthropic_thinking_replay model=%s rounds=%s rebuilt=%s",
            model,
            len(rounds),
            replayed.rebuilt,
        )
    position = 0
    for role, value in turns:
        if role == "assistant":
            _append_message(messages, "assistant", replayed.content[position])
            position += 1
        else:
            _append_message(messages, role, [_repair_tool_result(block, replayed.tool_use_ids) for block in value])


def _repair_tool_result(block: dict[str, Any], tool_use_ids: dict[str, str]) -> dict[str, Any]:
    if block.get("type") == "tool_result" and block.get("tool_use_id") in tool_use_ids:
        return {**block, "tool_use_id": tool_use_ids[block["tool_use_id"]]}
    return block


def _responses_item_to_blocks(item: Any) -> tuple[str, list[dict[str, Any]]]:
    item_type = item.get("type", "message") if isinstance(item, dict) else type(item).__name__
    if item_type == "function_call":
        return "assistant", [_tool_use_block(item)]
    if item_type == "function_call_output":
        return "user", [_tool_result_block(item)]
    if item_type != "message":
        raise _unsupported_request_error(f"Claude 目前不支援輸入項目「{item_type}」")
    role = item.get("role")
    if role in ("system", "developer"):
        role = "system"
    elif role not in ("user", "assistant"):
        raise _unsupported_request_error(f"Claude 不支援角色「{role}」")
    blocks = _content_blocks(item.get("content"))
    if role == "system" and any(block["type"] != "text" for block in blocks):
        raise _unsupported_request_error("Claude 的系統指示只能是文字")
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
            raise _unsupported_request_error("Claude 目前不支援檔案附件，請改貼文字或圖片")
        elif part_type in ("input_audio", "audio"):
            raise _unsupported_request_error("Claude 不支援語音輸入，請改用文字")
        else:
            raise _unsupported_request_error(f"Claude 目前不支援內容「{part_type}」")
    return blocks


def _image_block(part: dict[str, Any]) -> dict[str, Any]:
    url = part.get("image_url")
    if isinstance(url, dict):  # chat-style {"image_url": {"url": ...}}
        url = url.get("url")
    if not isinstance(url, str) or not url:
        # A file_id points into OpenAI's file store, which Anthropic cannot read.
        raise _unsupported_request_error("Claude 只能接收網址或內嵌的圖片，不支援以檔案 ID 傳圖")
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


def _max_tokens(body: dict[str, Any]) -> int:
    """The first limit the body sets: the Responses name, then the chat names some clients send."""
    for name in ("max_output_tokens", "max_completion_tokens", "max_tokens"):
        value = body.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return DEFAULT_MAX_TOKENS


def _unsupported_request_error(message: str) -> UpstreamServiceError:
    """The router's own 400 for a request Claude cannot take; raised before any upstream call."""
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
    # Tool input arrives as JSON text in pieces, kept per block index. It is parsed into the block's
    # `input` on block stop, so `content` always holds plain Anthropic content blocks; the raw text
    # stays the Responses `arguments`, so streamed deltas add up to the finished arguments.
    _tool_json: dict[int, str] = field(default_factory=dict, repr=False)

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
            elif delta_type == "input_json_delta":
                index = _block_index(event)
                self._tool_json[index] = self._tool_json.get(index, "") + str(delta.get("partial_json") or "")
        elif kind == "content_block_stop":
            raw = self._tool_json.get(_block_index(event), "")
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

    def thinking_summaries(self) -> list[str]:
        """The summarized text of each thinking block, in order (``display: "summarized"``)."""
        return [str(block.get("thinking") or "") for block in self.content if block.get("type") == "thinking"]

    def item_id(self, prefix: str) -> str:
        """A stable output item id for this message, so streamed items match the completed reply."""
        if not self._id_suffix:
            self._id_suffix = self.id.removeprefix("msg_") or uuid.uuid4().hex
        return f"{prefix}_{self._id_suffix}"

    def tool_arguments(self, index: int) -> str:
        """The Responses `arguments` for the tool_use block at ``index``: Claude's own JSON text."""
        raw = self._tool_json.get(index)
        if raw:
            return raw
        tool_input = self.content[index].get("input")
        return json.dumps(tool_input if isinstance(tool_input, dict) else {}, ensure_ascii=False)

    def _block_at(self, event: dict[str, Any]) -> dict[str, Any]:
        index = _block_index(event)
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


def responses_usage_from_anthropic(usage: dict[str, int]) -> dict[str, Any]:
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
            output.append(_responses_reasoning_item(message, model=model))
        elif kind == "text":
            output.append(_responses_message_item(message))
        else:
            output.append(_responses_function_call_item(message, _tool_block_index(kind)))
    if len(output) == 1:
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
        "usage": responses_usage_from_anthropic(message.usage),
    }


class ResponsesStream:
    """Turns Anthropic stream events into Responses stream events, as they arrive.

    Thinking streams as reasoning summary events on one reasoning item (one summary part per
    thinking block); text streams as output text on one assistant message item; each tool use
    streams as function call arguments on its own function_call item. Items are
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
        self._notice = ""  # a Readable Upstream Error that ended the stream early

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        self.message.apply(event)
        kind = event.get("type")
        if kind == "message_start":
            # The reasoning item always comes first: it carries the round's envelope (ADR 0093).
            created = self._event("response.created", response=self._response_shell())
            return [created, *self._open_item("thinking")]
        if kind == "content_block_start":
            return self._block_started(event)
        if kind == "content_block_delta":
            return self._block_delta(event)
        if kind == "content_block_stop":
            return self._block_stopped(event)
        return []

    @property
    def started(self) -> bool:
        return self._sequence > 0

    def fail(self, message: str) -> list[dict[str, Any]]:
        """Stream ``message`` as the end of the answer text; ``finish`` then closes the response.

        The notice stays out of ``self.message``: it is the router's text, not Claude's.
        """
        self._notice = ("\n\n" if self.message.text() else "") + message
        out = self._open_item("text") if "text" not in self._item_index else []
        out.append(
            self._event(
                "response.output_text.delta",
                item_id=self.message.item_id("msg"),
                output_index=self._item_index["text"],
                content_index=0,
                delta=self._notice,
            )
        )
        return out

    def finish(self) -> list[dict[str, Any]]:
        reply = responses_reply_from_message(self.message, model=self.model, created_at=self._created_at)
        if self._notice:
            # A round cut short is not one Claude can continue from: no envelope for it.
            reply["output"][0].pop("encrypted_content", None)
            messages = [item for item in reply["output"] if item["type"] == "message"]
            if not messages:
                messages = [_responses_message_item(self.message)]
                reply["output"].extend(messages)
            messages[0]["content"][0]["text"] += self._notice
        out: list[dict[str, Any]] = []
        for output_index, item in enumerate(reply["output"]):
            kind = self._kind_of(item)
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
        if kind == "tool_use":
            return self._open_item(_tool_kind(_block_index(event)))
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
        tool_kind = _tool_kind(_block_index(event))
        if delta.get("type") == "input_json_delta" and tool_kind in self._item_index:
            return [
                self._event(
                    "response.function_call_arguments.delta",
                    **self._tool_common(tool_kind),
                    delta=str(delta.get("partial_json") or ""),
                )
            ]
        return []

    def _block_stopped(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        tool_kind = _tool_kind(_block_index(event))
        if tool_kind in self._item_index:
            arguments = self.message.tool_arguments(_block_index(event))
            return [
                self._event(
                    "response.function_call_arguments.done", **self._tool_common(tool_kind), arguments=arguments
                )
            ]
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
        if kind.startswith("tool:"):
            item = _responses_function_call_item(self.message, _tool_block_index(kind), status="in_progress")
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

    def _tool_common(self, tool_kind: str) -> dict[str, Any]:
        block = self.message.content[_tool_block_index(tool_kind)]
        return {"item_id": _function_call_id(block), "output_index": self._item_index[tool_kind]}

    def _kind_of(self, item: dict[str, Any]) -> str:
        if item["type"] == "reasoning":
            return "thinking"
        if item["type"] == "function_call":
            for index, block in enumerate(self.message.content):
                if block.get("type") == "tool_use" and _function_call_id(block) == item["id"]:
                    return _tool_kind(index)
        return "text"

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
    """Output item kinds: the reasoning item first (it carries the round's envelope, ADR 0093),
    then the rest in first-arrival order. All thinking blocks share the reasoning item (one summary
    part each); all text blocks share one assistant message item; each tool_use block is its own
    function_call item, keyed ``tool:<block index>``."""
    kinds: list[str] = ["thinking"]
    for index, block in enumerate(message.content):
        kind = block.get("type")
        if kind == "text" and kind not in kinds:
            kinds.append(kind)
        elif kind == "tool_use":
            kinds.append(_tool_kind(index))
    return kinds


def _tool_kind(block_index: int) -> str:
    return f"tool:{block_index}"


def _tool_block_index(kind: str) -> int:
    return int(kind.removeprefix("tool:"))


def _function_call_id(block: dict[str, Any]) -> str:
    return f"fc_{block.get('id') or ''}"


def _responses_function_call_item(
    message: AnthropicMessage, index: int, *, status: str = "completed"
) -> dict[str, Any]:
    """A Responses function_call for one tool_use block. The Anthropic tool-use id is the call id."""
    block = message.content[index]
    return {
        "type": "function_call",
        "id": _function_call_id(block),
        "call_id": str(block.get("id") or ""),
        "name": str(block.get("name") or ""),
        "arguments": message.tool_arguments(index) if status == "completed" else "",
        "status": status,
    }


def _responses_reasoning_item(message: AnthropicMessage, *, model: str) -> dict[str, Any]:
    """The round's first item. Its summary is what Copilot shows; its ``encrypted_content`` is the
    envelope the next request rebuilds the round from. Copilot drops a reasoning item without one."""
    item: dict[str, Any] = {
        "type": "reasoning",
        "id": message.item_id("rs"),
        "summary": [{"type": "summary_text", "text": text} for text in message.thinking_summaries()],
    }
    envelope = encode_thinking_envelope(message.content, model=model)
    if envelope:
        item["encrypted_content"] = envelope
    return item


def _responses_message_item(message: AnthropicMessage) -> dict[str, Any]:
    return {
        "type": "message",
        "id": message.item_id("msg"),
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": message.text(), "annotations": []}],
    }


# ---------------------------------------------------------------------------
# 3b. Chat request translation: chat completions request -> Messages request
# ---------------------------------------------------------------------------


def messages_request_from_chat(req: ChatCompletionRequest) -> dict[str, Any]:
    """Build a Messages request from a chat completions request.

    The chat request is first restated as a Responses body, so both endpoints share one set of
    translation rules (and the same history always produces the same bytes). Fields are copied by
    allow-list, so sampling fields and Copilot's own fields never reach Anthropic.
    """
    return messages_request_from_responses(responses_body_from_chat(req))


def responses_body_from_chat(req: ChatCompletionRequest) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for message in req.messages:
        items.extend(_chat_message_items(message))
    extra = req.extra
    body: dict[str, Any] = {"model": req.model, "input": items, "n": extra.get("n")}
    max_tokens = extra.get("max_completion_tokens")
    body["max_output_tokens"] = max_tokens if max_tokens is not None else extra.get("max_tokens")
    if extra.get("reasoning_effort") is not None:
        body["reasoning"] = {"effort": extra["reasoning_effort"]}
    response_format = extra.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        json_schema = response_format.get("json_schema")
        schema = json_schema.get("schema") if isinstance(json_schema, dict) else None
        body["text"] = {"format": {"type": "json_schema", "schema": schema}}
    tools = [_responses_tool_from_chat(tool) for tool in extra.get("tools") or [] if isinstance(tool, dict)]
    if tools:
        body["tools"] = tools
        body["tool_choice"] = extra.get("tool_choice")
        body["parallel_tool_calls"] = extra.get("parallel_tool_calls")
    return body


def _responses_tool_from_chat(tool: dict[str, Any]) -> dict[str, Any]:
    # Chat nests the function under "function"; Responses keeps it flat.
    function = tool.get("function")
    if tool.get("type") != "function" or not isinstance(function, dict):
        return tool  # not a function tool: the shared translation drops it
    return {"type": "function", **function}


def _chat_message_items(message: ChatMessage) -> list[dict[str, Any]]:
    """One chat message as Responses input items.

    Each assistant message is one round and opens with a reasoning item whose ``encrypted_content``
    is the ``cot_id`` Copilot echoes from our ``reasoning_opaque``: the round's envelope, so the
    Responses replay rebuilds it. Echoed ``reasoning_content`` / ``reasoning`` / ``cot_summary`` are
    only summaries, never Claude's signed thinking, so they are not sent back (ADR 0093).
    """
    content = message.content if isinstance(message.content, (str, list)) else ""
    if message.role == "tool":
        return [{"type": "function_call_output", "call_id": message.tool_call_id or "", "output": content}]
    items: list[dict[str, Any]] = [{"type": "message", "role": message.role, "content": content}]
    if message.role == "assistant":
        items.insert(0, {"type": "reasoning", "encrypted_content": message.extra.get("cot_id")})
        for call in message.tool_calls or []:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                continue
            items.append(
                {
                    "type": "function_call",
                    "call_id": str(call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "arguments": function.get("arguments") or "{}",
                }
            )
    return items


# ---------------------------------------------------------------------------
# 4b. Chat reply translation: Anthropic events -> chat completion
# ---------------------------------------------------------------------------


def chat_usage_from_anthropic(usage: dict[str, int]) -> dict[str, Any]:
    """Chat usage; cache read and cache write count as prompt tokens, as on Responses."""
    responses_usage = responses_usage_from_anthropic(usage)
    return {
        "prompt_tokens": responses_usage["input_tokens"],
        "prompt_tokens_details": {"cached_tokens": responses_usage["input_tokens_details"]["cached_tokens"]},
        "completion_tokens": responses_usage["output_tokens"],
        "total_tokens": responses_usage["total_tokens"],
    }


def chat_reply_from_message(message: AnthropicMessage, *, model: str, created: int | None = None) -> dict[str, Any]:
    reply_message: dict[str, Any] = {"role": "assistant", "content": message.text()}
    reasoning = _chat_reasoning_content(message)
    if reasoning:
        reply_message["reasoning_content"] = reasoning
    envelope = encode_thinking_envelope(message.content, model=model)
    if envelope:
        reply_message["reasoning_opaque"] = envelope
    tool_calls = [
        _chat_tool_call(message, index) for index, block in enumerate(message.content) if block.get("type") == "tool_use"
    ]
    if tool_calls:
        reply_message["tool_calls"] = tool_calls
    return {
        "id": message.item_id("chatcmpl"),
        "object": "chat.completion",
        "created": created if created is not None else int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": reply_message, "finish_reason": _chat_finish_reason(message.stop_reason)}],
        "usage": chat_usage_from_anthropic(message.usage),
    }


_CHAT_THINKING_SEPARATOR = "\n\n"


def _chat_reasoning_content(message: AnthropicMessage) -> str:
    """Each thinking block's summary, in order; the stream joins them the same way."""
    return _CHAT_THINKING_SEPARATOR.join(text for text in message.thinking_summaries() if text)


def _chat_tool_call(message: AnthropicMessage, index: int) -> dict[str, Any]:
    # The Anthropic tool-use id is the chat tool call id, so the tool result goes back unchanged.
    block = message.content[index]
    return {
        "id": str(block.get("id") or ""),
        "type": "function",
        "function": {"name": str(block.get("name") or ""), "arguments": message.tool_arguments(index)},
    }


def _chat_finish_reason(stop_reason: str | None) -> str:
    if stop_reason == "tool_use":
        return "tool_calls"
    if stop_reason == "max_tokens":
        return "length"
    return "stop"


class ChatStream:
    """Turns Anthropic stream events into chat completion chunks, as they arrive.

    Thinking streams as ``delta.reasoning_content``, text as ``delta.content``. The last chunk
    carries the finish reason and the usage, which is where Token Usage reads it.
    """

    def __init__(self, *, model: str):
        self.model = model
        self.message = AnthropicMessage()
        self._created = int(time.time())
        self._started = False
        self._thinking_streamed = False
        self._separate_thinking = False
        self._tool_index: dict[int, int] = {}  # Anthropic block index -> chat tool call index
        self._failed = False  # a Readable Upstream Error ended the stream early

    @property
    def started(self) -> bool:
        return self._started

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        self.message.apply(event)
        kind = event.get("type")
        if kind == "message_start":
            self._started = True
            return [self._chunk({"role": "assistant", "content": ""})]
        if kind == "content_block_start":
            return self._block_started(event)
        if kind == "content_block_delta":
            return self._block_delta(event)
        return []

    def fail(self, message: str) -> list[dict[str, Any]]:
        """Stream ``message`` as the end of the answer text; ``finish`` then closes the stream.

        The stop reason stays unset (a refusal never reaches ``self.message``), so it finishes as ``stop``.
        """
        self._failed = True
        return [self._chunk({"content": ("\n\n" if self.message.text() else "") + message})]

    def finish(self) -> list[dict[str, Any]]:
        """The last chunk: finish reason, usage, and the round's envelope in ``reasoning_opaque``
        (ADR 0093), which Copilot sends back as ``cot_id``."""
        delta: dict[str, Any] = {}
        # A round cut short is not one Claude can continue from: no envelope for it, as on Responses.
        envelope = None if self._failed else encode_thinking_envelope(self.message.content, model=self.model)
        if envelope:
            delta["reasoning_opaque"] = envelope
        chunk = self._chunk(delta, finish_reason=_chat_finish_reason(self.message.stop_reason))
        chunk["usage"] = chat_usage_from_anthropic(self.message.usage)
        return [chunk]

    def _block_started(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        block = event.get("content_block") or {}
        if block.get("type") == "thinking":
            # A later thinking block's summary is set apart, as in the non-streaming reply.
            self._separate_thinking = self._thinking_streamed
        elif block.get("type") == "tool_use":
            tool_index = len(self._tool_index)
            self._tool_index[_block_index(event)] = tool_index
            call = {
                "index": tool_index,
                "id": str(block.get("id") or ""),
                "type": "function",
                "function": {"name": str(block.get("name") or ""), "arguments": ""},
            }
            return [self._chunk({"tool_calls": [call]})]
        return []

    def _block_delta(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        delta = event.get("delta") or {}
        if delta.get("type") == "thinking_delta" and delta.get("thinking"):
            text = str(delta["thinking"])
            if self._separate_thinking:
                text = _CHAT_THINKING_SEPARATOR + text
                self._separate_thinking = False
            self._thinking_streamed = True
            return [self._chunk({"reasoning_content": text})]
        if delta.get("type") == "text_delta" and delta.get("text"):
            return [self._chunk({"content": str(delta["text"])})]
        tool_index = self._tool_index.get(_block_index(event))
        if delta.get("type") == "input_json_delta" and delta.get("partial_json") and tool_index is not None:
            call = {"index": tool_index, "function": {"arguments": str(delta["partial_json"])}}
            return [self._chunk({"tool_calls": [call]})]
        return []

    def _chunk(self, delta: dict[str, Any], *, finish_reason: str | None = None) -> dict[str, Any]:
        return {
            "id": self.message.item_id("chatcmpl"),
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }


def _encode_chat_chunk(chunk: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
