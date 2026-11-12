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
