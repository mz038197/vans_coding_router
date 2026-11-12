"""`/v1/chat/completions` against Anthropic, through the gateway's public interface (#131)."""

import json

import pytest

from infrastructure.test_anthropic_gateway import (
    _FakeAnthropic,
    _gateway,
    _sse,
    _text_reply,
    _thinking_reply,
    _tool_use_reply,
    _two_tool_uses_reply,
)
from src.domain.entities.chat import ChatCompletionRequest, ChatMessage


def _chat(*messages: ChatMessage, stream: bool = False, **extra) -> ChatCompletionRequest:
    return ChatCompletionRequest(model="claude-opus-5-5", messages=list(messages), stream=stream, extra=extra)


@pytest.mark.asyncio
async def test_a_text_chat_request_returns_claudes_answer_as_a_chat_completion(monkeypatch):
    fake = _FakeAnthropic(_text_reply("Hello there", usage={"input_tokens": 12, "cache_read_input_tokens": 30}))
    gateway = _gateway(monkeypatch, fake)

    reply = await gateway.chat_completions_nonstream(
        _chat(ChatMessage(role="system", content="Be brief."), ChatMessage(role="user", content="Say hello"))
    )

    assert fake.sent["messages"] == [{"role": "user", "content": "Say hello"}]
    assert fake.sent["system"] == "Be brief."
    assert fake.sent["max_tokens"] == 32000
    assert fake.sent["stream"] is True
    assert reply["object"] == "chat.completion"
    assert reply["model"] == "claude-opus-5-5"
    assert reply["choices"] == [
        {"index": 0, "message": {"role": "assistant", "content": "Hello there"}, "finish_reason": "stop"}
    ]
    assert reply["usage"]["prompt_tokens"] == 42
    assert reply["usage"]["completion_tokens"] == 7
    assert reply["usage"]["total_tokens"] == 49
    assert reply["usage"]["prompt_tokens_details"] == {"cached_tokens": 30}


_CHAT_READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
}


@pytest.mark.asyncio
async def test_a_chat_tool_loop_with_images_becomes_the_matching_messages_request(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.chat_completions_nonstream(
        _chat(
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "open the file in this picture"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            ),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "toolu_01abc",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                    }
                ],
            ),
            ChatMessage(role="tool", tool_call_id="toolu_01abc", content="print('hi')"),
            tools=[_CHAT_READ_FILE_TOOL],
            tool_choice={"type": "function", "function": {"name": "read_file"}},
            parallel_tool_calls=False,
        )
    )

    assert fake.sent["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "open the file in this picture"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
            ],
        },
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_01abc", "name": "read_file", "input": {"path": "a.py"}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_01abc", "content": "print('hi')"}],
        },
    ]
    assert fake.sent["tools"] == [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]
    assert fake.sent["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limits", "sent"),
    [({}, 32000), ({"max_completion_tokens": 900}, 900), ({"max_tokens": 700}, 700)],
)
async def test_max_completion_tokens_and_max_tokens_both_set_claudes_max_tokens(monkeypatch, limits, sent):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.chat_completions_nonstream(_chat(ChatMessage(role="user", content="hi"), **limits))

    assert fake.sent["max_tokens"] == sent


@pytest.mark.asyncio
async def test_reasoning_effort_and_a_json_schema_response_format_reach_output_config(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}

    await gateway.chat_completions_nonstream(
        _chat(
            ChatMessage(role="user", content="hi"),
            reasoning_effort="minimal",
            response_format={"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
        )
    )

    assert fake.sent["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}


@pytest.mark.asyncio
async def test_copilot_and_sampling_fields_never_reach_claude(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.chat_completions_nonstream(
        _chat(
            ChatMessage(role="user", content="hi", extra={"copilot_cache_control": {"type": "ephemeral"}}),
            temperature=0.2,
            top_p=0.9,
            presence_penalty=1,
            stream_options={"include_usage": True},
            copilot_references=[{"type": "file"}],
            copilot_confirmations=[],
            copilot_cache_control={"type": "ephemeral"},
            response_format={"type": "text"},
        )
    )

    assert set(fake.sent) == {"model", "messages", "max_tokens", "stream", "cache_control", "thinking"}
    assert fake.sent["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_", "says"),
    [
        (
            _chat(ChatMessage(role="user", content=[{"type": "file", "file": {"file_id": "file-1"}}])),
            "檔案",
        ),
        (
            _chat(
                ChatMessage(
                    role="user", content=[{"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}}]
                )
            ),
            "語音",
        ),
        (_chat(ChatMessage(role="user", content="hi"), n=2), "n > 1"),
    ],
)
async def test_file_audio_and_several_choices_are_refused_without_calling_claude(monkeypatch, request_, says):
    from src.domain.errors import UpstreamServiceError

    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    with pytest.raises(UpstreamServiceError) as caught:
        await gateway.chat_completions_nonstream(request_)

    assert caught.value.status_code == 400
    assert says in caught.value.user_facing_message()
    assert fake.requests == []


@pytest.mark.asyncio
async def test_echoed_reasoning_on_assistant_messages_is_never_sent_as_thinking(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.chat_completions_nonstream(
        _chat(
            ChatMessage(role="user", content="hi"),
            ChatMessage(
                role="assistant",
                content="Hello",
                extra={"reasoning_content": "Plan.", "reasoning": "Plan.", "cot_summary": "Plan."},
            ),
            ChatMessage(role="user", content="again"),
        )
    )

    assert fake.sent["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "again"},
    ]


@pytest.mark.asyncio
async def test_a_claude_tool_use_comes_back_as_a_chat_tool_call_with_the_anthropic_id(monkeypatch):
    fake = _FakeAnthropic(_tool_use_reply())
    gateway = _gateway(monkeypatch, fake)

    reply = await gateway.chat_completions_nonstream(
        _chat(ChatMessage(role="user", content="open a.py"), tools=[_CHAT_READ_FILE_TOOL])
    )

    choice = reply["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Let me look."
    assert choice["message"]["tool_calls"] == [
        {"id": "toolu_01abc", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}
    ]


@pytest.mark.asyncio
async def test_the_thinking_summary_comes_back_in_reasoning_content(monkeypatch):
    fake = _FakeAnthropic(_thinking_reply("Plan the greeting.", "Hello!"))
    gateway = _gateway(monkeypatch, fake)

    reply = await gateway.chat_completions_nonstream(_chat(ChatMessage(role="user", content="hi")))

    message = reply["choices"][0]["message"]
    assert message["content"] == "Hello!"
    assert message["reasoning_content"] == "Plan the greeting."


async def _chat_chunks(gateway, request: ChatCompletionRequest) -> list[dict]:
    raw = b"".join([chunk async for chunk in gateway.chat_completions_stream(request)])
    frames = [frame for frame in raw.decode().split("\n\n") if frame.strip()]
    assert frames[-1] == "data: [DONE]"
    chunks = []
    for frame in frames[:-1]:
        assert frame.startswith("data: ")
        chunks.append(json.loads(frame.removeprefix("data: ")))
    return chunks


def _deltas(chunks: list[dict], key: str) -> str:
    return "".join(str(c["choices"][0]["delta"].get(key) or "") for c in chunks if c["choices"])


@pytest.mark.asyncio
async def test_a_streaming_chat_request_streams_the_thinking_summary_then_the_answer_then_usage(monkeypatch):
    fake = _FakeAnthropic(
        _thinking_reply(
            "Plan the greeting.",
            "Hello!",
            usage={"input_tokens": 20, "cache_read_input_tokens": 100, "output_tokens": 1},
        )
    )
    gateway = _gateway(monkeypatch, fake)

    chunks = await _chat_chunks(gateway, _chat(ChatMessage(role="user", content="hi"), stream=True))

    assert fake.sent["stream"] is True
    assert {chunk["object"] for chunk in chunks} == {"chat.completion.chunk"}
    assert len({chunk["id"] for chunk in chunks}) == 1
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert _deltas(chunks, "reasoning_content") == "Plan the greeting."
    assert _deltas(chunks, "content") == "Hello!"
    first_text = next(i for i, c in enumerate(chunks) if c["choices"][0]["delta"].get("content"))
    last_thinking = max(i for i, c in enumerate(chunks) if c["choices"][0]["delta"].get("reasoning_content"))
    assert last_thinking < first_text
    final = chunks[-1]
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["usage"] == {
        "prompt_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 100},
        "completion_tokens": 40,
        "total_tokens": 160,
    }
    assert all("usage" not in chunk for chunk in chunks[:-1])
    assert [c["choices"][0]["finish_reason"] for c in chunks[:-1]] == [None] * (len(chunks) - 1)


@pytest.mark.asyncio
async def test_streamed_tool_uses_stream_as_chat_tool_calls_with_the_anthropic_ids(monkeypatch):
    fake = _FakeAnthropic(_two_tool_uses_reply())
    gateway = _gateway(monkeypatch, fake)

    chunks = await _chat_chunks(
        gateway, _chat(ChatMessage(role="user", content="open both"), stream=True, tools=[_CHAT_READ_FILE_TOOL])
    )

    assert _deltas(chunks, "content") == "Reading both."
    calls: dict[int, dict] = {}
    for chunk in chunks:
        for piece in chunk["choices"][0]["delta"].get("tool_calls") or []:
            call = calls.setdefault(piece["index"], {"id": None, "name": None, "arguments": ""})
            if piece.get("id"):
                assert call["id"] is None
                call["id"] = piece["id"]
                assert piece["type"] == "function"
                call["name"] = piece["function"]["name"]
            call["arguments"] += piece["function"].get("arguments") or ""
    assert calls == {
        0: {"id": "toolu_A", "name": "read_file", "arguments": '{"path": "a.py"}'},
        1: {"id": "toolu_B", "name": "read_file", "arguments": '{"path": "b.py"}'},
    }
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ending", "readable"),
    [
        (
            {"type": "message_delta", "delta": {"stop_reason": "refusal"}, "usage": {"output_tokens": 3}},
            "Claude 拒絕回應這個請求，請換個說法再試",
        ),
        ({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, "Overloaded"),
    ],
)
async def test_an_error_mid_stream_finishes_the_chat_stream_with_a_readable_message(monkeypatch, ending, readable):
    fake = _FakeAnthropic(
        _sse(
            {"type": "message_start", "message": {"id": "msg_04", "model": "claude-opus-5-5", "usage": {}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Sure, here"}},
            ending,
            {"type": "message_stop"},
        )
    )
    gateway = _gateway(monkeypatch, fake)

    chunks = await _chat_chunks(gateway, _chat(ChatMessage(role="user", content="hi"), stream=True))

    assert _deltas(chunks, "content") == f"Sure, here\n\n{readable}"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert "usage" in chunks[-1]
    assert gateway.pool_status()["keys"][0]["in_flight"] == 0


@pytest.mark.asyncio
async def test_a_refusal_before_any_text_streams_only_the_readable_message(monkeypatch):
    fake = _FakeAnthropic(
        _sse(
            {"type": "message_start", "message": {"id": "msg_05", "model": "claude-opus-5-5", "usage": {}}},
            {"type": "message_delta", "delta": {"stop_reason": "refusal"}, "usage": {"output_tokens": 0}},
            {"type": "message_stop"},
        )
    )
    gateway = _gateway(monkeypatch, fake)

    chunks = await _chat_chunks(gateway, _chat(ChatMessage(role="user", content="hi"), stream=True))

    assert _deltas(chunks, "content") == "Claude 拒絕回應這個請求，請換個說法再試"


@pytest.mark.asyncio
async def test_a_streaming_chat_upstream_error_raises_before_any_chunk(monkeypatch):
    from src.domain.errors import UpstreamServiceError

    fake = _FakeAnthropic(
        json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}).encode(),
        status=400,
    )
    gateway = _gateway(monkeypatch, fake)
    stream = gateway.chat_completions_stream(_chat(ChatMessage(role="user", content="hi"), stream=True))

    with pytest.raises(UpstreamServiceError) as caught:
        await stream.__anext__()

    assert caught.value.status_code == 400
    assert caught.value.user_facing_message() == "bad"
    assert gateway.pool_status()["keys"][0]["in_flight"] == 0


@pytest.mark.asyncio
async def test_a_non_streaming_refusal_raises_the_readable_upstream_error(monkeypatch):
    from src.domain.errors import UpstreamServiceError

    fake = _FakeAnthropic(
        _sse(
            {"type": "message_start", "message": {"id": "msg_06", "model": "claude-opus-5-5", "usage": {}}},
            {"type": "message_delta", "delta": {"stop_reason": "refusal"}, "usage": {"output_tokens": 0}},
            {"type": "message_stop"},
        )
    )
    gateway = _gateway(monkeypatch, fake)

    with pytest.raises(UpstreamServiceError) as caught:
        await gateway.chat_completions_nonstream(_chat(ChatMessage(role="user", content="hi")))

    assert caught.value.status_code == 400
    assert caught.value.user_facing_message() == "Claude 拒絕回應這個請求，請換個說法再試"


@pytest.mark.asyncio
async def test_several_thinking_blocks_read_the_same_streamed_and_not_streamed(monkeypatch):
    def thinking(index: int, text: str) -> list[dict]:
        return [
            {"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": text}},
            {"type": "content_block_stop", "index": index},
        ]

    body = _sse(
        {"type": "message_start", "message": {"id": "msg_07", "model": "claude-opus-5-5", "usage": {}}},
        *thinking(0, "First."),
        *thinking(1, "Second."),
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    )
    gateway = _gateway(monkeypatch, _FakeAnthropic(body))

    reply = await gateway.chat_completions_nonstream(_chat(ChatMessage(role="user", content="hi")))
    chunks = await _chat_chunks(gateway, _chat(ChatMessage(role="user", content="hi"), stream=True))

    assert reply["choices"][0]["message"]["reasoning_content"] == "First.\n\nSecond."
    assert _deltas(chunks, "reasoning_content") == "First.\n\nSecond."
    assert reply["choices"][0]["finish_reason"] == chunks[-1]["choices"][0]["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_the_same_chat_history_always_produces_the_same_messages_bytes(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    def history() -> ChatCompletionRequest:
        return _chat(
            ChatMessage(role="system", content="Be brief."),
            ChatMessage(role="user", content="open a.py"),
            ChatMessage(
                role="assistant",
                content="Let me look.",
                tool_calls=[{"id": "toolu_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
                extra={"reasoning_content": "varies per client"},
            ),
            ChatMessage(role="tool", tool_call_id="toolu_1", content="print('hi')"),
            tools=[_CHAT_READ_FILE_TOOL],
        )

    await gateway.chat_completions_nonstream(history())
    first = fake.requests[-1].content
    request = history()
    request.messages[2].extra["reasoning_content"] = "something else"
    await gateway.chat_completions_nonstream(request)

    assert fake.requests[-1].content == first
