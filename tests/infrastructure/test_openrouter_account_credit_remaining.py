import httpx
import pytest

from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway

OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"


def _openrouter_gateway(monkeypatch, *, envs: dict[str, str], usage_client: httpx.AsyncClient):
    for name, value in envs.items():
        monkeypatch.setenv(name, value)
    return OpenAICompatibleGateway(
        ProviderSettings(
            name="openrouter",
            type="openai_compatible",
            base_url="https://openrouter.ai/api/v1",
            api_key_envs=tuple(envs),
            max_concurrent_per_key=6,
        ),
        timeout=30.0,
        usage_client=usage_client,
    )


def _usage_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)


def _bearer_key(request: httpx.Request) -> str:
    auth = request.headers.get("authorization") or ""
    return auth.removeprefix("Bearer ").strip()


def _credits_payload(total_credits: float, total_usage: float) -> dict:
    return {
        "data": {
            "total_credits": total_credits,
            "total_usage": total_usage,
            "limit_remaining": 1,
            "usage": 99,
        }
    }


@pytest.mark.asyncio
async def test_overlay_attaches_account_credit_remaining_and_hides_secrets(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == OPENROUTER_CREDITS_URL
        key = _bearer_key(request)
        calls.append(key)
        if key == "secret-a":
            return httpx.Response(200, json=_credits_payload(110, 94.5))
        return httpx.Response(200, json=_credits_payload(10, 1.5))

    client = _usage_client(handler)
    openrouter = _openrouter_gateway(
        monkeypatch,
        envs={"OPENROUTER_API_KEY": "secret-a", "OPENROUTER_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"openrouter": openrouter})
    status = await routing.overlay_account_credit_remaining(routing.pool_status(limited_only=True))
    keys = status["providers"]["openrouter"]["pool"]["keys"]
    assert [item["account_credit_remaining"] for item in keys] == [15.5, 8.5]
    assert "limit_remaining" not in keys[0]
    assert "included_monthly_usage" not in keys[0]
    assert [item["in_flight"] for item in keys] == [0, 0]
    assert [item["quarantined"] for item in keys] == [False, False]
    dumped = str(status)
    assert "secret-a" not in dumped
    assert "secret-b" not in dumped
    assert set(calls) == {"secret-a", "secret-b"}
    await client.aclose()


@pytest.mark.asyncio
async def test_one_key_credits_error_leaves_other_key_and_in_flight(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if _bearer_key(request) == "secret-a":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json=_credits_payload(10, 1.5))

    client = _usage_client(handler)
    openrouter = _openrouter_gateway(
        monkeypatch,
        envs={"OPENROUTER_API_KEY": "secret-a", "OPENROUTER_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"openrouter": openrouter})
    status = await routing.overlay_account_credit_remaining(routing.pool_status(limited_only=True))
    keys = status["providers"]["openrouter"]["pool"]["keys"]
    assert keys[0]["account_credit_remaining"] is None
    assert keys[1]["account_credit_remaining"] == 8.5
    assert [item["in_flight"] for item in keys] == [0, 0]
    assert [item["quarantined"] for item in keys] == [False, False]
    await client.aclose()


@pytest.mark.asyncio
async def test_successful_credit_remaining_is_cached_failures_are_retried(monkeypatch):
    script = {"secret-a": [8.5], "secret-b": [httpx.Response(401), 0.0]}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = _bearer_key(request)
        calls.append(key)
        next_value = script[key].pop(0)
        if isinstance(next_value, httpx.Response):
            return next_value
        usage = 1.5 if next_value == 8.5 else 10
        return httpx.Response(200, json=_credits_payload(10, usage))

    client = _usage_client(handler)
    openrouter = _openrouter_gateway(
        monkeypatch,
        envs={"OPENROUTER_API_KEY": "secret-a", "OPENROUTER_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"openrouter": openrouter})
    first = await routing.overlay_account_credit_remaining(routing.pool_status(limited_only=True))
    second = await routing.overlay_account_credit_remaining(routing.pool_status(limited_only=True))
    assert first["providers"]["openrouter"]["pool"]["keys"][0]["account_credit_remaining"] == 8.5
    assert first["providers"]["openrouter"]["pool"]["keys"][1]["account_credit_remaining"] is None
    assert second["providers"]["openrouter"]["pool"]["keys"][0]["account_credit_remaining"] == 8.5
    assert second["providers"]["openrouter"]["pool"]["keys"][1]["account_credit_remaining"] == 0.0
    assert calls.count("secret-a") == 1
    assert calls.count("secret-b") == 2
    await client.aclose()
