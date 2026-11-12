import json

import httpx
import pytest

from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.anthropic_gateway import AnthropicGateway


def _sse(*events: dict) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def _text_reply(text: str, *, usage: dict | None = None) -> bytes:
    start_usage = usage or {"input_tokens": 12, "output_tokens": 1}
    return _sse(
        {
            "type": "message_start",
            "message": {
                "id": "msg_01",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [],
                "stop_reason": None,
                "usage": start_usage,
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "ping"},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[:3]}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[3:]}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    )


class _FakeAnthropic:
    def __init__(self, body: bytes = b"", status: int = 200):
        self.body = body or _text_reply("Hello there")
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            self.status,
            content=self.body,
            headers={"content-type": "text/event-stream"},
        )

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


def _gateway(monkeypatch, fake) -> AnthropicGateway:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-a")
    monkeypatch.delenv("ANTHROPIC_API_KEY_2", raising=False)
    return AnthropicGateway(
        ProviderSettings(
            name="anthropic",
            type="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key_envs=("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_2"),
            max_concurrent_per_key=10,
        ),
        timeout=5.0,
        transport=httpx.MockTransport(fake),
    )


def _assistant_text(reply: dict) -> str:
    return "".join(
        part["text"]
        for item in reply["output"]
        if item["type"] == "message"
        for part in item["content"]
        if part["type"] == "output_text"
    )


@pytest.mark.asyncio
async def test_a_text_responses_request_returns_claudes_answer(monkeypatch):
    fake = _FakeAnthropic(_text_reply("Hello there"))
    gateway = _gateway(monkeypatch, fake)

    reply = await gateway.responses_create({"model": "claude-opus-5-5", "input": "Say hello"})

    assert reply["object"] == "response"
    assert reply["status"] == "completed"
    assert reply["model"] == "claude-opus-5-5"
    assert _assistant_text(reply) == "Hello there"
    assert fake.requests[-1].url == "https://api.anthropic.com/v1/messages"
    assert fake.requests[-1].headers["x-api-key"] == "key-a"
    assert fake.sent["stream"] is True
    assert fake.sent["model"] == "claude-opus-5-5"
    assert fake.sent["messages"] == [{"role": "user", "content": "Say hello"}]
    await gateway.shutdown()


@pytest.mark.asyncio
async def test_every_messages_request_pins_the_anthropic_version(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    assert fake.requests[-1].headers["anthropic-version"] == "2026-10-21"


@pytest.mark.asyncio
async def test_max_tokens_defaults_to_32000_and_follows_the_sent_limit(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})
    assert fake.sent["max_tokens"] == 32000

    await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi", "max_output_tokens": 900})
    assert fake.sent["max_tokens"] == 900


@pytest.mark.asyncio
async def test_sampling_fields_are_dropped_and_prompt_caching_is_automatic(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create(
        {"model": "claude-opus-5-5", "input": "hi", "temperature": 0.2, "top_p": 0.9, "top_k": 40}
    )

    assert not {"temperature", "top_p", "top_k"} & fake.sent.keys()
    assert fake.sent["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_instructions_and_message_items_become_system_and_turns(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create(
        {
            "model": "claude-opus-5-5",
            "instructions": "Be brief.",
            "input": [
                {"type": "message", "role": "developer", "content": "Answer in English."},
                {"role": "user", "content": [{"type": "input_text", "text": "Hi"}]},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Hello"}]},
                {"type": "message", "role": "user", "content": "How are you?"},
            ],
        }
    )

    assert fake.sent["system"] == "Be brief.\n\nAnswer in English."
    assert fake.sent["messages"] == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "How are you?"},
    ]


@pytest.mark.asyncio
async def test_usage_maps_to_openai_usage_with_cache_tokens_counted_as_input(monkeypatch):
    fake = _FakeAnthropic(
        _text_reply(
            "Hello there",
            usage={
                "input_tokens": 10,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 30,
                "output_tokens": 1,
            },
        )
    )
    gateway = _gateway(monkeypatch, fake)

    reply = await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    assert reply["usage"]["input_tokens"] == 240
    assert reply["usage"]["input_tokens_details"]["cached_tokens"] == 200
    assert reply["usage"]["output_tokens"] == 7
    assert reply["usage"]["total_tokens"] == 247


@pytest.mark.asyncio
async def test_an_upstream_error_is_raised_before_any_reply(monkeypatch):
    from src.domain.errors import UpstreamServiceError

    fake = _FakeAnthropic(
        json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}).encode(),
        status=400,
    )
    gateway = _gateway(monkeypatch, fake)

    with pytest.raises(UpstreamServiceError) as caught:
        await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    assert caught.value.status_code == 400
    assert caught.value.user_facing_message() == "bad"


@pytest.mark.asyncio
async def test_unsupported_capabilities_are_refused_without_calling_anthropic(monkeypatch):
    from src.domain.errors import (
        ImageGenerationNotSupportedError,
        SpeechTranscriptionNotSupportedError,
        UpstreamServiceError,
    )

    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    with pytest.raises(ImageGenerationNotSupportedError):
        await gateway.images_create({"prompt": "cat"})
    with pytest.raises(UpstreamServiceError):
        await gateway.embeddings_create({"input": "x"})
    with pytest.raises(SpeechTranscriptionNotSupportedError):
        await gateway.audio_transcriptions_create({}, ("a.wav", b"", None))
    assert fake.requests == []


@pytest.mark.asyncio
async def test_an_exhausted_key_is_quarantined_and_the_next_key_answers(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["x-api-key"] == "key-a":
            return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})
        return httpx.Response(200, content=_text_reply("From key b"))

    monkeypatch.setenv("ANTHROPIC_API_KEY_2", "key-b")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-a")
    gateway = AnthropicGateway(
        ProviderSettings(
            name="anthropic",
            type="anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key_envs=("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_2"),
            max_concurrent_per_key=10,
        ),
        transport=httpx.MockTransport(handler),
    )

    reply = await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    assert _assistant_text(reply) == "From key b"
    keys = gateway.pool_status()["keys"]
    assert [key["label"] for key in keys] == ["ANTHROPIC 1", "ANTHROPIC 2"]
    assert [key["quarantined"] for key in keys] == [True, False]
    assert [key["in_flight"] for key in keys] == [0, 0]


@pytest.mark.asyncio
async def test_anthropic_model_ids_route_to_the_anthropic_gateway(monkeypatch):
    from src.infrastructure.gateways.routing_gateway import RoutingGateway

    fake = _FakeAnthropic(_text_reply("Routed"))
    router = RoutingGateway({"anthropic": _gateway(monkeypatch, fake)})

    reply = await router.responses_create({"model": "anthropic@claude-opus-5-5", "input": "hi"})

    assert _assistant_text(reply) == "Routed"
    assert fake.sent["model"] == "claude-opus-5-5"


_READ_FILE_TOOL = {
    "type": "function",
    "name": "read_file",
    "description": "Read a file",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    "strict": False,
}


@pytest.mark.asyncio
async def test_function_tools_become_anthropic_tools(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi", "tools": [_READ_FILE_TOOL]})

    assert fake.sent["tools"] == [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_choice", "sent"),
    [
        ("required", {"type": "auto"}),
        ({"type": "function", "name": "read_file"}, {"type": "auto"}),
        ("auto", {"type": "auto"}),
        ("none", {"type": "none"}),
    ],
)
async def test_a_forced_tool_choice_is_sent_as_auto(monkeypatch, tool_choice, sent):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create(
        {"model": "claude-opus-5-5", "input": "hi", "tools": [_READ_FILE_TOOL], "tool_choice": tool_choice}
    )

    assert fake.sent["tool_choice"] == sent


@pytest.mark.asyncio
async def test_parallel_tool_calls_false_disables_parallel_tool_use(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create(
        {"model": "claude-opus-5-5", "input": "hi", "tools": [_READ_FILE_TOOL], "parallel_tool_calls": False}
    )

    assert fake.sent["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}


def _tool_use_reply() -> bytes:
    return _sse(
        {
            "type": "message_start",
            "message": {"id": "msg_02", "model": "claude-opus-5-5", "content": [], "usage": {"input_tokens": 20}},
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Let me look."}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_01abc", "name": "read_file", "input": {}},
        },
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"pa'}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": 'th": "a.py"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 30}},
        {"type": "message_stop"},
    )


@pytest.mark.asyncio
async def test_a_claude_tool_use_comes_back_as_a_function_call_with_the_same_call_id(monkeypatch):
    fake = _FakeAnthropic(_tool_use_reply())
    gateway = _gateway(monkeypatch, fake)

    reply = await gateway.responses_create({"model": "claude-opus-5-5", "input": "open a.py", "tools": [_READ_FILE_TOOL]})

    assert reply["status"] == "completed"
    assert [item["type"] for item in reply["output"]] == ["message", "function_call"]
    assert _assistant_text(reply) == "Let me look."
    call = reply["output"][1]
    assert call["call_id"] == "toolu_01abc"
    assert call["name"] == "read_file"
    assert json.loads(call["arguments"]) == {"path": "a.py"}
    assert call["status"] == "completed"


_TOOL_LOOP_HISTORY = [
    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "open a.py"}]},
    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Let me look."}]},
    {
        "type": "function_call",
        "id": "fc_toolu_01abc",
        "call_id": "toolu_01abc",
        "name": "read_file",
        "arguments": '{"path": "a.py"}',
        "status": "completed",
    },
    {"type": "function_call_output", "call_id": "toolu_01abc", "output": "print('hi')"},
]


@pytest.mark.asyncio
async def test_a_function_call_output_becomes_a_matching_tool_result(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create(
        {"model": "claude-opus-5-5", "input": _TOOL_LOOP_HISTORY, "tools": [_READ_FILE_TOOL]}
    )

    assert fake.sent["messages"] == [
        {"role": "user", "content": "open a.py"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                {"type": "tool_use", "id": "toolu_01abc", "name": "read_file", "input": {"path": "a.py"}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_01abc", "content": "print('hi')"}],
        },
    ]


@pytest.mark.asyncio
async def test_a_tool_result_can_carry_text_and_images(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)
    history = _TOOL_LOOP_HISTORY[:-1] + [
        {
            "type": "function_call_output",
            "call_id": "toolu_01abc",
            "output": [
                {"type": "input_text", "text": "screenshot:"},
                {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0K"},
            ],
        }
    ]

    await gateway.responses_create({"model": "claude-opus-5-5", "input": history, "tools": [_READ_FILE_TOOL]})

    assert fake.sent["messages"][-1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_01abc",
            "content": [
                {"type": "text", "text": "screenshot:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0K"}},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_the_same_history_always_produces_the_same_messages_bytes(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)
    body = {"model": "claude-opus-5-5", "input": _TOOL_LOOP_HISTORY, "tools": [_READ_FILE_TOOL]}

    await gateway.responses_create(json.loads(json.dumps(body)))
    await gateway.responses_create(json.loads(json.dumps(body)))

    assert fake.requests[0].content == fake.requests[1].content


@pytest.mark.asyncio
async def test_image_inputs_reach_claude_as_image_blocks(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create(
        {
            "model": "claude-opus-5-5",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "What is wrong here?"},
                        {"type": "input_image", "image_url": "data:image/jpeg;base64,/9j/4AAQ", "detail": "auto"},
                        {"type": "input_image", "image_url": "https://example.com/error.png"},
                    ],
                }
            ],
        }
    )

    assert fake.sent["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is wrong here?"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "/9j/4AAQ"}},
                {"type": "image", "source": {"type": "url", "url": "https://example.com/error.png"}},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_system_messages_become_anthropic_system_content(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create(
        {
            "model": "claude-opus-5-5",
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": "You are Copilot."}]},
                {"role": "developer", "content": "Use tabs."},
                {"role": "user", "content": "hi"},
            ],
        }
    )

    assert fake.sent["system"] == "You are Copilot.\n\nUse tabs."
    assert fake.sent["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "says"),
    [
        (
            {"input": [{"role": "user", "content": [{"type": "input_file", "file_data": "JVBERi0", "filename": "a.pdf"}]}]},
            "檔案",
        ),
        (
            {"input": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": "UklG", "format": "wav"}}]}]},
            "語音",
        ),
        ({"input": "hi", "n": 2}, "n > 1"),
    ],
)
async def test_file_audio_and_several_choices_are_refused_without_calling_anthropic(monkeypatch, body, says):
    from src.domain.errors import UpstreamServiceError

    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    with pytest.raises(UpstreamServiceError) as caught:
        await gateway.responses_create({"model": "claude-opus-5-5", **body})

    assert caught.value.status_code == 400
    assert says in caught.value.user_facing_message()
    assert fake.requests == []


@pytest.mark.asyncio
async def test_a_json_schema_text_format_is_sent_as_structured_outputs(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    }

    await gateway.responses_create(
        {
            "model": "claude-opus-5-5",
            "input": "Name this commit",
            "text": {"format": {"type": "json_schema", "name": "commit", "schema": schema, "strict": True}},
        }
    )

    assert fake.sent["output_config"] == {"format": {"type": "json_schema", "schema": schema}}


@pytest.mark.asyncio
async def test_a_plain_text_format_sends_no_output_format(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi", "text": {"format": {"type": "text"}}})

    assert "format" not in fake.sent.get("output_config", {})
