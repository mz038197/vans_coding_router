"""Anthropic in the Upstream Model Catalog and the Portal pool tile (#130)."""

import json

import httpx
import pytest

from src.application.upstream_model_catalog import UpstreamModelCatalogMemory
from src.domain.errors import UpstreamServiceError, UpstreamTransportError
from src.infrastructure.config import ProviderSettings, RouterSettings
from src.infrastructure.gateways.anthropic_gateway import AnthropicGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway

_PROVIDER = ProviderSettings(
    name="anthropic",
    type="anthropic",
    base_url="https://api.anthropic.com/v1",
    api_key_envs=("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_2"),
    max_concurrent_per_key=10,
    acquire_delay_ms=0,
)

_MODEL_LIST = {
    "data": [
        {"type": "model", "id": "claude-opus-5-5", "display_name": "Claude Opus 5.5"},
        {"type": "model", "id": "claude-haiku-5", "display_name": ""},
    ],
    "has_more": False,
    "first_id": "claude-opus-5-5",
    "last_id": "claude-haiku-5",
}


class _FakeAnthropic:
    def __init__(self, status: int = 200, body: object = None):
        self.status = status
        self.body = _MODEL_LIST if body is None else body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                402,
                json={"error": {"type": "billing_error", "message": "insufficient credits"}},
            )
        return httpx.Response(self.status, content=json.dumps(self.body).encode())


def _gateway(monkeypatch, fake, *, two_keys: bool = False) -> AnthropicGateway:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-a")
    if two_keys:
        monkeypatch.setenv("ANTHROPIC_API_KEY_2", "key-b")
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY_2", raising=False)
    return AnthropicGateway(_PROVIDER, timeout=5.0, transport=httpx.MockTransport(fake))


@pytest.mark.asyncio
async def test_models_lists_active_models_in_one_call(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake)

    listed = await gateway.models()

    assert listed["data"] == [
        {"id": "claude-opus-5-5", "name": "Claude Opus 5.5"},
        {"id": "claude-haiku-5", "name": "claude-haiku-5"},
    ]
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/models"
    assert dict(request.url.params) == {"lifecycle": "active", "limit": "1000"}
    assert request.headers["x-api-key"] == "key-a"
    assert request.headers["anthropic-version"]
    await gateway.shutdown()


@pytest.mark.asyncio
async def test_a_failed_models_call_raises_the_upstream_error(monkeypatch):
    fake = _FakeAnthropic(status=503, body={"error": {"type": "api_error", "message": "down"}})
    gateway = _gateway(monkeypatch, fake)

    with pytest.raises(UpstreamServiceError) as caught:
        await gateway.models()

    assert caught.value.status_code == 503
    await gateway.shutdown()


@pytest.mark.asyncio
async def test_an_unreachable_models_call_raises_a_transport_error(monkeypatch):
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    gateway = _gateway(monkeypatch, unreachable)

    with pytest.raises(UpstreamTransportError):
        await gateway.models()
    await gateway.shutdown()


@pytest.mark.asyncio
async def test_the_catalog_lists_anthropic_models_under_all_models_only(monkeypatch):
    gateway = _gateway(monkeypatch, _FakeAnthropic())
    settings = RouterSettings(providers={"anthropic": _PROVIDER})
    memory = UpstreamModelCatalogMemory(
        lambda: settings, RoutingGateway({"anthropic": gateway}), retry_delays_sec=()
    )

    await memory.fill()

    assert [item["id"] for item in memory.read("all")["models"]] == [
        "anthropic@claude-opus-5-5",
        "anthropic@claude-haiku-5",
    ]
    for kind in ("image", "embeddings", "speech", "speech_transcription", "decisions"):
        assert memory.read(kind)["models"] == []
    await gateway.shutdown()


async def _portal_pools(routing: RoutingGateway) -> dict:
    status = routing.pool_status(limited_only=True)
    for overlay in (
        routing.overlay_included_monthly_usage,
        routing.overlay_account_credit_remaining,
        routing.overlay_key_monthly_limit,
    ):
        status = await overlay(status)
    return status["providers"]["anthropic"]["pool"]


@pytest.mark.asyncio
async def test_the_pool_tile_reports_quarantine_and_release_without_a_money_meter(monkeypatch):
    fake = _FakeAnthropic()
    gateway = _gateway(monkeypatch, fake, two_keys=True)
    routing = RoutingGateway({"anthropic": gateway})
    # Both keys run out of credit, so both land in Key Quarantine.
    with pytest.raises(UpstreamServiceError):
        await gateway.responses_create({"model": "claude-opus-5-5", "input": "hi"})

    pool = await _portal_pools(routing)

    assert pool["in_flight_total"] == 0
    assert pool["capacity"] == 20
    assert [key["label"] for key in pool["keys"]] == ["ANTHROPIC 1", "ANTHROPIC 2"]
    assert [key["quarantined"] for key in pool["keys"]] == [True, True]
    for money in ("included_monthly_usage", "account_credit_remaining", "key_monthly_limit"):
        assert money not in pool
        assert all(money not in key for key in pool["keys"])

    await routing.release_key_quarantine("anthropic", 1)

    pool = await _portal_pools(routing)
    assert [key["quarantined"] for key in pool["keys"]] == [True, False]
    assert routing.is_key_quarantined("anthropic", 1) is False
    await gateway.shutdown()
