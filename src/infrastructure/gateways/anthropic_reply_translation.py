"""Reply translation for the Anthropic gateway (ADR 0092): Anthropic stream events into the student's reply.

``AnthropicMessage`` folds the events into one assistant message. Non-stream replies are built from
it; ``ResponsesStream`` and ``ChatStream`` emit the Responses or chat stream as events arrive, and
finish from the same builders, so a streamed reply always equals the non-streamed one.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Protocol

from src.infrastructure.gateways.anthropic_thinking_envelope import encode_thinking_envelope


# ---------------------------------------------------------------------------
# The assembled message, the stream protocol and Responses replies
# ---------------------------------------------------------------------------


class ReplyStream(Protocol):
    """A streaming emitter: Anthropic events in, the student's stream events out (Responses or chat)."""

    @property
    def started(self) -> bool: ...

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]: ...

    def fail(self, message: str) -> list[dict[str, Any]]: ...

    def finish(self) -> list[dict[str, Any]]: ...


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


async def assemble_message(events: AsyncGenerator[dict[str, Any], None]) -> AnthropicMessage:
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


def encode_responses_event(event: dict[str, Any]) -> bytes:
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
# Chat completion replies
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


def encode_chat_chunk(chunk: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
