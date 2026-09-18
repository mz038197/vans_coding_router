import httpx
import pytest

from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway

OLLAMA_USAGE_URL = "https://ollama.com/api/usage"


def _ollama_gateway(monkeypatch, *, envs: dict[str, str], usage_client: httpx.AsyncClient):
    for name, value in envs.items():
        monkeypatch.setenv(name, value)
    return OpenAICompatibleGateway(
        ProviderSettings(
            name="ollama_cloud",
            type="openai_compatible",
            base_url="https://ollama.com/v1",
            api_key_envs=tuple(envs),
            max_concurrent_per_key=3,
        ),
        timeout=30.0,
        usage_client=usage_client,
    )


def _usage_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)


def _bearer_key(request: httpx.Request) -> str:
    auth = request.headers.get("authorization") or ""
    return auth.removeprefix("Bearer ").strip()


def _usage_payload(monthly: float, *, extra_remaining: float | None = 99.0) -> dict:
    payload: dict = {
        "activity": {"cost": "9.99"},
        "limits": {
            "monthly": {"usage": monthly, "models": []},
        },
    }
    if extra_remaining is not None:
        payload["extra_usage"] = {"remaining": extra_remaining}
    return payload


@pytest.mark.asyncio
async def test_overlay_attaches_included_monthly_usage_and_hides_secrets(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == OLLAMA_USAGE_URL
        key = _bearer_key(request)
        calls.append(key)
        weekly = 0.125 if key == "secret-a" else 0.0
        return httpx.Response(200, json=_usage_payload(weekly))

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    snapshot = routing.pool_status(limited_only=True)
    status = await routing.overlay_included_monthly_usage(snapshot)
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert [item["included_monthly_usage"] for item in keys] == [0.125, 0.0]
    assert "extra_usage_remaining" not in keys[0]
    assert [item["in_flight"] for item in keys] == [0, 0]
    dumped = str(status)
    assert "secret-a" not in dumped
    assert "secret-b" not in dumped
    assert set(calls) == {"secret-a", "secret-b"}
    await client.aclose()


@pytest.mark.asyncio
async def test_one_key_usage_error_leaves_other_key_and_in_flight(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        key = _bearer_key(request)
        if key == "secret-a":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json=_usage_payload(0.08))

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    status = await routing.overlay_included_monthly_usage(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert len(keys) == 2
    assert keys[0]["included_monthly_usage"] is None
    assert keys[1]["included_monthly_usage"] == 0.08
    assert keys[0]["in_flight"] == 0
    assert keys[1]["in_flight"] == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_usage_timeout_marks_only_that_key_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if _bearer_key(request) == "secret-a":
            raise httpx.TimeoutException("usage timed out")
        return httpx.Response(200, json=_usage_payload(0.03))

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    status = await routing.overlay_included_monthly_usage(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert keys[0]["included_monthly_usage"] is None
    assert keys[1]["included_monthly_usage"] == 0.03
    await client.aclose()


@pytest.mark.asyncio
async def test_session_only_usage_is_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "limits": {
                    "session": {"usage": 0.4, "models": []},
                }
            },
        )

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    status = await routing.overlay_included_monthly_usage(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert len(keys) == 1
    assert keys[0]["included_monthly_usage"] is None
    await client.aclose()


@pytest.mark.asyncio
async def test_unset_second_key_fetches_only_configured_key(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(_bearer_key(request))
        return httpx.Response(200, json=_usage_payload(0.01, extra_remaining=None))

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    status = await routing.overlay_included_monthly_usage(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert [item["label"] for item in keys] == ["OLLAMA_CLOUD 1"]
    assert calls == ["secret-a"]
    await client.aclose()


@pytest.mark.asyncio
async def test_successful_weekly_usage_is_cached_failures_are_retried(monkeypatch):
    usage_by_call = {"secret-a": [0.07], "secret-b": [httpx.Response(401), 0.04]}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = _bearer_key(request)
        calls.append(key)
        next_value = usage_by_call[key].pop(0)
        if isinstance(next_value, httpx.Response):
            return next_value
        return httpx.Response(200, json=_usage_payload(next_value))

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    first = await routing.overlay_included_monthly_usage(routing.pool_status(limited_only=True))
    second = await routing.overlay_included_monthly_usage(routing.pool_status(limited_only=True))
    assert first["providers"]["ollama_cloud"]["pool"]["keys"][0]["included_monthly_usage"] == 0.07
    assert first["providers"]["ollama_cloud"]["pool"]["keys"][1]["included_monthly_usage"] is None
    assert second["providers"]["ollama_cloud"]["pool"]["keys"][0]["included_monthly_usage"] == 0.07
    assert second["providers"]["ollama_cloud"]["pool"]["keys"][1]["included_monthly_usage"] == 0.04
    assert calls.count("secret-a") == 1
    assert calls.count("secret-b") == 2
    await client.aclose()
