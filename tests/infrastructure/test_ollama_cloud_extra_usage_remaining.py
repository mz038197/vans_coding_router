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


@pytest.mark.asyncio
async def test_overlay_attaches_extra_usage_remaining_and_hides_secrets(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == OLLAMA_USAGE_URL
        key = _bearer_key(request)
        calls.append(key)
        remaining = 12.5 if key == "secret-a" else 0.0
        return httpx.Response(
            200,
            json={
                "extra_usage": {"remaining": remaining},
                "activity": {"cost": "9.99"},
                "limits": {
                    "session": {"usage": 0.1, "models": []},
                    "weekly": {"usage": 0.2, "models": []},
                },
            },
        )

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    snapshot = routing.pool_status(limited_only=True)
    status = await routing.overlay_extra_usage_remaining(snapshot)
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert [item["extra_usage_remaining"] for item in keys] == [12.5, 0.0]
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
        return httpx.Response(200, json={"extra_usage": {"remaining": 8}})

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    status = await routing.overlay_extra_usage_remaining(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert len(keys) == 2
    assert keys[0]["extra_usage_remaining"] is None
    assert keys[1]["extra_usage_remaining"] == 8.0
    assert keys[0]["in_flight"] == 0
    assert keys[1]["in_flight"] == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_usage_timeout_marks_only_that_key_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if _bearer_key(request) == "secret-a":
            raise httpx.TimeoutException("usage timed out")
        return httpx.Response(200, json={"extra_usage": {"remaining": 3}})

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    status = await routing.overlay_extra_usage_remaining(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert keys[0]["extra_usage_remaining"] is None
    assert keys[1]["extra_usage_remaining"] == 3.0
    await client.aclose()


@pytest.mark.asyncio
async def test_session_weekly_only_usage_is_unavailable_not_a_percent(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "limits": {
                    "session": {"usage": 0.4, "models": []},
                    "weekly": {"usage": 0.8, "models": []},
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
    status = await routing.overlay_extra_usage_remaining(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert len(keys) == 1
    assert keys[0]["extra_usage_remaining"] is None
    await client.aclose()


@pytest.mark.asyncio
async def test_unset_second_key_fetches_only_configured_key(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(_bearer_key(request))
        return httpx.Response(200, json={"extra_usage": {"remaining": 1}})

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    status = await routing.overlay_extra_usage_remaining(routing.pool_status(limited_only=True))
    keys = status["providers"]["ollama_cloud"]["pool"]["keys"]
    assert [item["label"] for item in keys] == ["OLLAMA_CLOUD 1"]
    assert calls == ["secret-a"]
    await client.aclose()


@pytest.mark.asyncio
async def test_successful_remaining_is_cached_failures_are_retried(monkeypatch):
    remaining_by_call = {"secret-a": [7.0], "secret-b": [httpx.Response(401), 4.0]}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = _bearer_key(request)
        calls.append(key)
        next_value = remaining_by_call[key].pop(0)
        if isinstance(next_value, httpx.Response):
            return next_value
        return httpx.Response(200, json={"extra_usage": {"remaining": next_value}})

    client = _usage_client(handler)
    ollama = _ollama_gateway(
        monkeypatch,
        envs={"OLLAMA_CLOUD_API_KEY": "secret-a", "OLLAMA_CLOUD_API_KEY_2": "secret-b"},
        usage_client=client,
    )
    routing = RoutingGateway({"ollama_cloud": ollama})
    first = await routing.overlay_extra_usage_remaining(routing.pool_status(limited_only=True))
    second = await routing.overlay_extra_usage_remaining(routing.pool_status(limited_only=True))
    assert first["providers"]["ollama_cloud"]["pool"]["keys"][0]["extra_usage_remaining"] == 7.0
    assert first["providers"]["ollama_cloud"]["pool"]["keys"][1]["extra_usage_remaining"] is None
    assert second["providers"]["ollama_cloud"]["pool"]["keys"][0]["extra_usage_remaining"] == 7.0
    assert second["providers"]["ollama_cloud"]["pool"]["keys"][1]["extra_usage_remaining"] == 4.0
    assert calls.count("secret-a") == 1
    assert calls.count("secret-b") == 2
    await client.aclose()
