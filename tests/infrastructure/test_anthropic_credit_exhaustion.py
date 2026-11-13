"""Anthropic Credit Exhaustion, busy responses and refusals through the gateway (#129)."""

import json

import httpx
import pytest

from src.application.vcr_auto_walk import VcrAutoWalk
from src.domain.errors import UpstreamServiceError
from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.anthropic_gateway import AnthropicGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway


def _sse(*events: dict) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def _reply(text: str, *, stop_reason: str = "end_turn") -> httpx.Response:
    body = _sse(
        {
            "type": "message_start",
            "message": {"id": "msg_01", "model": "claude-opus-5-5", "content": [], "usage": {"input_tokens": 5}},
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    )
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


def _error(status: int, kind: str, message: str, **extra) -> httpx.Response:
    return httpx.Response(status, json={"type": "error", "error": {"type": kind, "message": message, **extra}})


CREDIT_EXHAUSTION = {
    "billing_error": lambda: _error(402, "billing_error", "There is a problem with your billing."),
    "spend_limit": lambda: _error(
        400, "invalid_request_error", "You have reached your specified API usage limits. You will regain access on 2026-12-01."
    ),
    "workspace_spend_limit": lambda: _error(
        400,
        "invalid_request_error",
        "You have reached your specified workspace API usage limits. You will regain access on 2026-12-01.",
    ),
    "tier_spend_cap": lambda: _error(
        429,
        "rate_limit_error",
        "You have reached your monthly spend limit.",
        details={"error_code": "enforced_spend_limit_reached"},
    ),
    "credit_balance": lambda: _error(
        400,
        "invalid_request_error",
        "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.",
    ),
}


def _gateway(monkeypatch, handler, *, name: str = "anthropic") -> AnthropicGateway:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-a")
    monkeypatch.setenv("ANTHROPIC_API_KEY_2", "key-b")
    return AnthropicGateway(
        ProviderSettings(
            name=name,
            type="anthropic",
            base_url=f"https://{name}.test/v1",
            api_key_envs=("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_2"),
            max_concurrent_per_key=10,
            acquire_delay_ms=0,
            quarantine_ttl_sec=3600,
        ),
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )


def _text(reply: dict) -> str:
    return "".join(
        part["text"] for item in reply["output"] if item["type"] == "message" for part in item["content"]
    )


def _quarantined(gateway: AnthropicGateway) -> list[bool]:
    return [key["quarantined"] for key in gateway.pool_status()["keys"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", sorted(CREDIT_EXHAUSTION))
async def test_credit_exhaustion_quarantines_the_key_and_fails_over(monkeypatch, signal):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["x-api-key"] == "key-a":
            return CREDIT_EXHAUSTION[signal]()
        return _reply("From key b")

    gateway = _gateway(monkeypatch, handler)

    reply = await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    assert _text(reply) == "From key b"
    assert _quarantined(gateway) == [True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "response"),
    [
        (429, lambda: httpx.Response(
            429,
            headers={"retry-after": "7"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited"}},
        )),
        (529, lambda: _error(529, "overloaded_error", "Overloaded")),
    ],
)
async def test_a_plain_429_and_a_529_do_not_quarantine(monkeypatch, status, response):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-api-key"])
        return response()

    gateway = _gateway(monkeypatch, handler)

    with pytest.raises(UpstreamServiceError) as caught:
        await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    assert caught.value.status_code == status
    assert _quarantined(gateway) == [False, False]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_when_every_key_is_exhausted_vcr_auto_moves_to_the_next_model_id(monkeypatch):
    exhausted = _gateway(monkeypatch, lambda request: CREDIT_EXHAUSTION["credit_balance"](), name="anthropic")
    backup = _gateway(monkeypatch, lambda request: _reply("From the backup"), name="backup")
    router = RoutingGateway({"anthropic": exhausted, "backup": backup})
    model_ids = ["anthropic@claude-opus-5-5", "backup@claude-sonnet-5"]

    async def call(model_id: str):
        return await router.responses_create({"model": model_id, "input": "hi"})

    first = await VcrAutoWalk().run(model_ids, call)
    assert first.model_id == "backup@claude-sonnet-5"
    assert _text(first.value) == "From the backup"
    assert _quarantined(exhausted) == [True, True]

    # Both keys are already quarantined: the next walk still moves on without calling Anthropic.
    second = await VcrAutoWalk().run(model_ids, call)
    assert second.model_id == "backup@claude-sonnet-5"


@pytest.mark.asyncio
async def test_every_key_exhausted_reads_as_anthropics_message(monkeypatch):
    gateway = _gateway(monkeypatch, lambda request: CREDIT_EXHAUSTION["credit_balance"]())

    for _ in range(2):
        with pytest.raises(UpstreamServiceError) as caught:
            await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})
        assert caught.value.status_code == 402
        assert caught.value.user_facing_message().startswith("Your credit balance is too low")


@pytest.mark.asyncio
async def test_a_refusal_stop_reason_is_a_readable_upstream_error(monkeypatch):
    gateway = _gateway(monkeypatch, lambda request: _reply("I can't", stop_reason="refusal"))

    with pytest.raises(UpstreamServiceError) as caught:
        await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    assert caught.value.status_code == 400
    assert "Claude" in caught.value.user_facing_message()
    assert _quarantined(gateway) == [False, False]


@pytest.mark.asyncio
async def test_a_refusal_ends_the_vcr_auto_walk(monkeypatch):
    backup_calls: list[httpx.Request] = []

    def backup_handler(request: httpx.Request) -> httpx.Response:
        backup_calls.append(request)
        return _reply("From the backup")

    refusing = _gateway(monkeypatch, lambda request: _reply("", stop_reason="refusal"), name="anthropic")
    backup = _gateway(monkeypatch, backup_handler, name="backup")
    router = RoutingGateway({"anthropic": refusing, "backup": backup})

    async def call(model_id: str):
        return await router.responses_create({"model": model_id, "input": "hi"})

    with pytest.raises(UpstreamServiceError):
        await VcrAutoWalk().run(["anthropic@claude-opus-5-5", "backup@claude-sonnet-5"], call)

    assert backup_calls == []
