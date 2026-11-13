"""Request translation for the Anthropic gateway (ADR 0092): a student request into a Messages request.

Responses bodies translate directly; a chat completions request is first restated as a Responses
body, so both endpoints share one set of rules. The translation is deterministic, so the same
history always produces the same bytes (ADR 0093).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.domain.errors import UpstreamServiceError
from src.infrastructure.gateways.anthropic_thinking_envelope import AssistantRound, replay_assistant_rounds

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 32000


# ---------------------------------------------------------------------------
# Responses request -> Messages request
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
        system = [turn for turn in turns if isinstance(turn, _BlocksTurn) and turn.role == "system"]
        system_parts.extend(block["text"] for turn in system for block in turn.blocks)
        rest = [turn for turn in turns if not (isinstance(turn, _BlocksTurn) and turn.role == "system")]
        _append_replayed_turns(messages, rest, model=str(body.get("model") or ""))

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


@dataclass
class _BlocksTurn:
    """A system or user turn: content blocks sent as they are."""

    role: str  # "system" | "user"
    blocks: list[dict[str, Any]]


# A turn is a system or user turn, or one assistant round (rebuilt from its envelope on replay).
_Turn = _BlocksTurn | AssistantRound


def _responses_turns(items: list[Any]) -> list[_Turn]:
    """Responses input items as turns.

    A round is one assistant reply: the run of assistant items (reasoning, message, function_call)
    between other turns. A reasoning item opens a new round, since every reply this router makes
    starts with one; its ``encrypted_content`` is the round's envelope and its summary is ignored.
    """
    turns: list[_Turn] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "reasoning":
            turns.append(AssistantRound(envelope=item.get("encrypted_content")))
            continue
        role, blocks = _responses_item_to_blocks(item)
        if role == "assistant":
            if not turns or not isinstance(turns[-1], AssistantRound):
                turns.append(AssistantRound())
            turns[-1].blocks.extend(blocks)
        else:
            turns.append(_BlocksTurn(role, blocks))
    return turns


def _append_replayed_turns(messages: list[dict[str, Any]], turns: list[_Turn], *, model: str) -> None:
    """Append user turns and assistant rounds, rebuilding each round from its envelope (ADR 0093)."""
    rounds = [turn for turn in turns if isinstance(turn, AssistantRound)]
    replayed = replay_assistant_rounds(rounds, model=model)
    if rounds:
        logger.info(
            "anthropic_thinking_replay model=%s rounds=%s rebuilt=%s",
            model,
            len(rounds),
            replayed.rebuilt,
        )
    position = 0
    for turn in turns:
        if isinstance(turn, AssistantRound):
            _append_message(messages, "assistant", replayed.content[position])
            position += 1
        else:
            blocks = [_repair_tool_result(block, replayed.tool_use_ids) for block in turn.blocks]
            _append_message(messages, turn.role, blocks)


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
# Chat completions request -> Responses body
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
