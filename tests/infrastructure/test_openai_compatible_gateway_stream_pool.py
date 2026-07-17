from __future__ import annotations

import asyncio
from contextlib import aclosing
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("STREAM_POOL_KEY", "secret")
    return OpenAICompatibleGateway(
        ProviderSettings(
            name="ollama_cloud",
            type="openai_compatible",
            base_url="https://example.test/v1",
            api_key_env="STREAM_POOL_KEY",
            max_concurrent_per_key=1,
            queue_timeout_sec=0.2,
            acquire_delay_ms=0,
        ),
        timeout=5.0,
    )


def _mock_stream_response(chunks: list[bytes]):
    response = MagicMock()
    response.status_code = 200

    async def aiter_bytes():
        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0)

    response.aiter_bytes = aiter_bytes
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.mark.asyncio
async def test_stream_releases_pool_slot_when_consumer_aclose_early(gateway):
    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_mock_stream_response([b"one", b"two", b"three"]))
    gateway._client = mock_client

    stream = gateway._stream("POST", "/responses", json={"model": "m"})
    first = await stream.__anext__()
    assert first == b"one"
    assert gateway._pool.in_flight_snapshot() == [1]

    await stream.aclose()
    assert gateway._pool.in_flight_snapshot() == [0]

    # Slot is reusable immediately (would time out if leaked).
    index = await asyncio.wait_for(gateway._pool.acquire(), timeout=0.2)
    await gateway._pool.release(index)


@pytest.mark.asyncio
async def test_stream_releases_pool_slot_with_aclosing_break(gateway):
    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_mock_stream_response([b"one", b"two", b"three"]))
    gateway._client = mock_client

    async with aclosing(gateway._stream("POST", "/responses", json={"model": "m"})) as stream:
        async for chunk in stream:
            assert chunk == b"one"
            break

    assert gateway._pool.in_flight_snapshot() == [0]


@pytest.mark.asyncio
async def test_responses_create_stream_releases_pool_on_early_aclose(gateway):
    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_mock_stream_response([b"a", b"b"]))
    gateway._client = mock_client

    with patch.object(gateway, "_prepare_responses_body", AsyncMock(side_effect=lambda body: dict(body))):
        stream = gateway.responses_create_stream({"model": "m", "input": "hi"})
        assert await stream.__anext__() == b"a"
        assert gateway._pool.in_flight_snapshot() == [1]
        await stream.aclose()

    assert gateway._pool.in_flight_snapshot() == [0]
