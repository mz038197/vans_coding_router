from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.domain.errors import ServiceUnavailableError, UpstreamServiceError
from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("POOL_REL_KEY", "secret")
    return OpenAICompatibleGateway(
        ProviderSettings(
            name="ollama_cloud",
            type="openai_compatible",
            base_url="https://example.test/v1",
            api_key_env="POOL_REL_KEY",
            max_concurrent_per_key=1,
            queue_timeout_sec=0.2,
            acquire_delay_ms=0,
        ),
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_request_releases_slot_on_upstream_http_error_path(gateway):
    """Non-httpx errors still go through finally; slot must not stick."""
    response = MagicMock()
    response.status_code = 200
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(return_value=response)

    original_release = gateway._pool.release
    released = {"ok": False}

    async def tracking_release(index: int) -> None:
        released["ok"] = True
        await original_release(index)

    gateway._pool.release = tracking_release  # type: ignore[method-assign]
    await gateway._request("GET", "/models")
    assert released["ok"] is True
    assert gateway._pool.in_flight_snapshot() == [0]


@pytest.mark.asyncio
async def test_stream_releases_slot_on_upstream_service_error(gateway):
    response = MagicMock()
    response.status_code = 502
    response.aread = AsyncMock(return_value=b"bad gateway")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    gateway._client = MagicMock()
    gateway._client.stream = MagicMock(return_value=response)

    with pytest.raises(UpstreamServiceError):
        async for _ in gateway._stream("POST", "/responses", json={}):
            pass

    assert gateway._pool.in_flight_snapshot() == [0]


@pytest.mark.asyncio
async def test_request_preserves_primary_error_if_release_raises(gateway):
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(side_effect=httpx.ConnectError("boom"))

    original_release = gateway._pool.release

    async def boom_release(index: int) -> None:
        await original_release(index)
        raise RuntimeError("release failed")

    gateway._pool.release = boom_release  # type: ignore[method-assign]

    with pytest.raises(ServiceUnavailableError, match="unavailable"):
        await gateway._request("POST", "/chat/completions", json={})

    assert gateway._pool.in_flight_snapshot() == [0]
