"""Thinking envelope round trip on the chat path (#132, ADR 0093), through the gateway's public interface."""

import json

import pytest

from infrastructure.test_anthropic_thinking_envelope import MODEL, _envelope_of, _FakeAnthropic, _gateway, _reply
from src.domain.entities.chat import ChatCompletionRequest, ChatMessage


def _chat(*messages: ChatMessage, stream: bool = False, model: str = MODEL) -> ChatCompletionRequest:
    return ChatCompletionRequest(model=model, messages=list(messages), stream=stream, extra={"tools": [_READ_FILE]})


_READ_FILE = {
    "type": "function",
    "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
}


def _as_copilot_echo(reply_message: dict) -> ChatMessage:
    """A chat reply message as Copilot sends it back on the next request.

    Copilot trims trailing whitespace from the text, returns ``reasoning_opaque`` as ``cot_id`` and
    echoes the summary as plain text in ``cot_summary`` (and sometimes ``reasoning_content``).
    """
    extra = {"cot_summary": reply_message.get("reasoning_content", ""), "reasoning_content": "echoed plan"}
    if reply_message.get("reasoning_opaque"):
        extra["cot_id"] = reply_message["reasoning_opaque"]
    return ChatMessage(
        role="assistant",
        content=(reply_message.get("content") or "").rstrip(),
        tool_calls=reply_message.get("tool_calls"),
        extra=extra,
    )


def _thought(n: int) -> list[dict]:
    return [
        {"type": "thinking", "thinking": f"Thinking about round {n}.", "signature": f"sig-{n}"},
        {"type": "text", "text": f"Answer {n}.  \n\n"},
    ]


def _tool_round(n: int) -> list[dict]:
    return [
        {"type": "thinking", "thinking": f"I need file {n}.", "signature": f"sig-tool-{n}"},
        {"type": "text", "text": f"Reading {n}. "},
        {"type": "tool_use", "id": f"toolu_{n}", "name": "read_file", "input": {"path": f"{n}.py"}},
    ]


def _assistant_turns(sent: dict) -> list:
    return [m["content"] for m in sent["messages"] if m["role"] == "assistant"]


def _without_thinking(blocks: list[dict]) -> list[dict]:
    kept = [dict(b) for b in blocks if b["type"] != "thinking"]
    for block in kept:
        if block["type"] == "text":
            block["text"] = block["text"].rstrip()  # Copilot's trimmed copy
    return kept


async def _stream_chunks(gateway, request: ChatCompletionRequest) -> list[dict]:
    raw = b"".join([chunk async for chunk in gateway.chat_completions_stream(request)])
    return [json.loads(frame.removeprefix("data: ")) for frame in raw.decode().split("\n\n") if frame.startswith("data: {")]


@pytest.mark.asyncio
async def test_the_next_chat_turn_replays_the_prior_assistant_turn_byte_for_byte(monkeypatch):
    blocks = _thought(1)
    fake = _FakeAnthropic(_reply(blocks))
    gateway = _gateway(monkeypatch, fake)
    first = await gateway.chat_completions_nonstream(_chat(ChatMessage(role="user", content="q1")))

    reply_message = first["choices"][0]["message"]
    assert reply_message["reasoning_content"] == "Thinking about round 1."
    assert reply_message["reasoning_opaque"]

    await gateway.chat_completions_nonstream(
        _chat(ChatMessage(role="user", content="q1"), _as_copilot_echo(reply_message), ChatMessage(role="user", content="q2"))
    )

    sent = fake.sent["messages"]
    assert sent[1] == {"role": "assistant", "content": blocks}
    assert json.dumps(sent[1]["content"]) == json.dumps(blocks)
    assert sent[2] == {"role": "user", "content": "q2"}


@pytest.mark.asyncio
async def test_the_final_stream_chunk_carries_the_same_envelope_as_the_non_streamed_reply(monkeypatch):
    blocks = _tool_round(1)
    fake = _FakeAnthropic(_reply(blocks, stop="tool_use"), _reply(blocks, stop="tool_use"))
    gateway = _gateway(monkeypatch, fake)
    request = _chat(ChatMessage(role="user", content="fix it"))

    chunks = await _stream_chunks(gateway, _chat(ChatMessage(role="user", content="fix it"), stream=True))
    non_stream = await gateway.chat_completions_nonstream(request)

    envelope = non_stream["choices"][0]["message"]["reasoning_opaque"]
    final = chunks[-1]["choices"][0]
    assert final["finish_reason"] == "tool_calls"
    assert final["delta"]["reasoning_opaque"] == envelope
    assert all("reasoning_opaque" not in chunk["choices"][0]["delta"] for chunk in chunks[:-1])

    streamed = {
        "content": "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks),
        "reasoning_opaque": final["delta"]["reasoning_opaque"],
        "tool_calls": non_stream["choices"][0]["message"]["tool_calls"],
    }
    tool_result = ChatMessage(role="tool", tool_call_id="toolu_1", content="data")
    await gateway.chat_completions_nonstream(
        _chat(ChatMessage(role="user", content="fix it"), _as_copilot_echo(streamed), tool_result)
    )

    assert fake.sent["messages"][1] == {"role": "assistant", "content": blocks}


def _earlier_turn(echo: ChatMessage) -> ChatMessage:
    """Copilot drops ``cot_id`` from assistant messages of earlier user turns; the plain-text echoes stay."""
    return ChatMessage(role=echo.role, content=echo.content, tool_calls=echo.tool_calls, extra={k: v for k, v in echo.extra.items() if k != "cot_id"})


@pytest.mark.asyncio
async def test_earlier_user_turns_go_without_thinking_while_the_current_tasks_rounds_keep_it(monkeypatch):
    earlier, rounds = _thought(1), [_tool_round(2), _tool_round(3)]
    fake = _FakeAnthropic(_reply(earlier), *[_reply(blocks, msg_id=f"msg_{n}", stop="tool_use") for n, blocks in enumerate(rounds)])
    gateway = _gateway(monkeypatch, fake)
    first = await gateway.chat_completions_nonstream(_chat(ChatMessage(role="user", content="q1")))
    history = [ChatMessage(role="user", content="q1"), _earlier_turn(_as_copilot_echo(first["choices"][0]["message"]))]
    history.append(ChatMessage(role="user", content="fix it"))
    for blocks in rounds:
        reply = await gateway.chat_completions_nonstream(_chat(*history))
        history.append(_as_copilot_echo(reply["choices"][0]["message"]))
        history.append(ChatMessage(role="tool", tool_call_id=blocks[-1]["id"], content="data"))

    reply = await gateway.chat_completions_nonstream(_chat(*history))

    assert reply["choices"][0]["finish_reason"] == "stop"
    assert _assistant_turns(fake.sent) == ["Answer 1.", *rounds]
    assert "echoed plan" not in json.dumps(fake.sent) and "Thinking about round 1." not in json.dumps(fake.sent)


@pytest.mark.asyncio
async def test_echoed_plain_text_reasoning_is_never_sent_as_thinking(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)
    echoed = {"cot_summary": "Plan A.", "reasoning_content": "Plan B.", "reasoning": "Plan C.", "reasoning_opaque": "x"}

    await gateway.chat_completions_nonstream(
        _chat(
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="Hello", extra=echoed),
            ChatMessage(role="user", content="again"),
        )
    )

    assert fake.sent["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "again"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_cot_id",
    [
        "not base64 at all!!",
        "cot_copilot_0123456789",
        _envelope_of(b"{not json"),
        _envelope_of({"v": 1, "model": MODEL, "content": [{"type": "thinking", "thinking": "x"}]}),
        _envelope_of({"v": 1, "model": "claude-sonnet-5-5", "content": [{"type": "text", "text": "Answer 1.  \n\n"}]}),
        {"id": "cot_1"},
        12345,
        "",
    ],
    ids=["garbage", "foreign", "not-json", "unsigned-thinking", "other-model", "object", "number", "empty"],
)
async def test_a_malformed_or_foreign_cot_id_counts_as_missing(monkeypatch, bad_cot_id):
    fake = _FakeAnthropic(_reply(_thought(1)))
    gateway = _gateway(monkeypatch, fake)
    first = await gateway.chat_completions_nonstream(_chat(ChatMessage(role="user", content="q1")))
    echo = _as_copilot_echo(first["choices"][0]["message"])
    echo.extra["cot_id"] = bad_cot_id

    reply = await gateway.chat_completions_nonstream(
        _chat(ChatMessage(role="user", content="q1"), echo, ChatMessage(role="user", content="q2"))
    )

    assert reply["choices"][0]["message"]["content"] == "ok"
    assert fake.sent["messages"] == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "Answer 1."},
        {"role": "user", "content": "q2"},
    ]


@pytest.mark.asyncio
async def test_an_input_transformation_on_a_chat_request_is_logged_with_its_reason(monkeypatch, caplog):
    dropped = {"type": "thinking_block_dropped", "message_index": 1, "content_index": 0, "reason": "prefix_mismatch"}
    fake = _FakeAnthropic(_reply([{"type": "text", "text": "ok"}], start_extra={"input_transformations": [dropped]}))
    gateway = _gateway(monkeypatch, fake)
    caplog.set_level("INFO", logger="src.infrastructure.gateways.anthropic_gateway")

    await _stream_chunks(gateway, _chat(ChatMessage(role="user", content="hi"), stream=True))

    logged = [r.getMessage() for r in caplog.records if "anthropic_input_transformation" in r.getMessage()]
    assert len(logged) == 1 and "reason=prefix_mismatch" in logged[0] and f"model={MODEL}" in logged[0]


@pytest.mark.asyncio
async def test_a_stream_cut_short_by_a_refusal_carries_no_envelope(monkeypatch):
    fake = _FakeAnthropic(_reply(_thought(1), stop="refusal"))
    gateway = _gateway(monkeypatch, fake)

    chunks = await _stream_chunks(gateway, _chat(ChatMessage(role="user", content="q1"), stream=True))

    final = chunks[-1]["choices"][0]
    assert final["finish_reason"] == "stop"
    assert all("reasoning_opaque" not in chunk["choices"][0]["delta"] for chunk in chunks)
