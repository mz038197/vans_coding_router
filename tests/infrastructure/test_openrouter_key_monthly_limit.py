import httpx
import pytest

from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"


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


def _bearer_key(request: httpx.Request) -> str:
    return (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()


def _key_payload(limit, remaining, reset="monthly") -> dict:
    return {"data": {"limit": limit, "limit_reset": reset, "limit_remaining": remaining, "usage": 99}}


@pytest.mark.asyncio
async def test_overlay_attaches_each_keys_monthly_limit_and_hides_secrets(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == OPENROUTER_KEY_URL
        key = _bearer_key(request)
        calls.append(key)
        if key == "secret-a":
            return httpx.Response(200, json=_key_payload(20, 11.8))
        return httpx.Response(200, json=_key_payload(None, None, reset=None))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)
    openrouter = _openrouter_gateway(
        monkeypatch,
        envs={"OPENROUTER_API_KEY": "secret-a", "OPENROUTER_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"openrouter": openrouter})

    status = await routing.overlay_key_monthly_limit(routing.pool_status(limited_only=True))
    again = await routing.overlay_key_monthly_limit(routing.pool_status(limited_only=True))

    keys = status["providers"]["openrouter"]["pool"]["keys"]
    assert keys[0]["key_monthly_limit"]["summary"] == "$8.20 of $20 used"
    assert keys[0]["key_monthly_limit"]["limit_usd"] == 20.0
    assert keys[1]["key_monthly_limit"] is None
    assert [item["in_flight"] for item in keys] == [0, 0]
    assert "secret" not in str(status)
    assert again["providers"]["openrouter"]["pool"]["keys"][0]["key_monthly_limit"]["used_usd"] == 8.2
    # A key with a cap is cached; a key without one is asked again so a newly set cap shows.
    assert calls.count("secret-a") == 1
    assert calls.count("secret-b") == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_key_document_error_leaves_that_key_without_a_meter(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if _bearer_key(request) == "secret-a":
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=_key_payload(10, 4))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)
    openrouter = _openrouter_gateway(
        monkeypatch,
        envs={"OPENROUTER_API_KEY": "secret-a", "OPENROUTER_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"openrouter": openrouter})

    status = await routing.overlay_key_monthly_limit(routing.pool_status(limited_only=True))

    keys = status["providers"]["openrouter"]["pool"]["keys"]
    assert keys[0]["key_monthly_limit"] is None
    assert keys[1]["key_monthly_limit"]["summary"] == "$6 of $10 used"
    await client.aclose()
