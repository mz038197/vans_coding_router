from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.errors import UpstreamServiceError
from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway


def _gateway(monkeypatch) -> OpenAICompatibleGateway:
    monkeypatch.setenv("K1", "key-a")
    monkeypatch.setenv("K2", "key-b")
    return OpenAICompatibleGateway(
        ProviderSettings(
            name="ollama_cloud",
            type="openai_compatible",
            base_url="https://example.test/v1",
            api_key_envs=("K1", "K2"),
            max_concurrent_per_key=3,
            acquire_delay_ms=0,
            quarantine_ttl_sec=3600,
        ),
        timeout=5.0,
    )


def _response(status_code: int, text: str = "", json_body=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_body is not None:
        response.json = MagicMock(return_value=json_body)
    else:
        response.json = MagicMock(side_effect=ValueError("no json"))
    return response


@pytest.mark.asyncio
async def test_request_failovers_to_second_key_on_extra_usage(monkeypatch):
    gateway = _gateway(monkeypatch)
    exhausted = _response(
        402,
        text='{"error":"extra usage balance is empty, add extra usage"}',
        json_body={"error": "extra usage balance is empty, add extra usage"},
    )
    ok = _response(200, text="{}", json_body={"ok": True})
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(side_effect=[exhausted, ok])

    response = await gateway._request("POST", "/chat/completions", json={"model": "x"})
    assert response.status_code == 200
    assert gateway._client.request.await_count == 2
    auth_headers = [call.kwargs["headers"]["Authorization"] for call in gateway._client.request.await_args_list]
    assert auth_headers == ["Bearer key-a", "Bearer key-b"] or auth_headers == [
        "Bearer key-b",
        "Bearer key-a",
    ]
    assert gateway._pool.status()["keys"][0]["quarantined"] or gateway._pool.status()["keys"][1]["quarantined"]
    assert gateway._pool.in_flight_snapshot() == [0, 0]


@pytest.mark.asyncio
async def test_request_failovers_to_second_key_on_credit_exhaustion(monkeypatch):
    gateway = _gateway(monkeypatch)
    exhausted = _response(
        402,
        text=(
            '{"error":{"code":402,"message":"Insufficient credits. Add more using '
            'https://openrouter.ai/credits","metadata":{"error_type":"payment_required"}}}'
        ),
        json_body={
            "error": {
                "code": 402,
                "message": "Insufficient credits. Add more using https://openrouter.ai/credits",
                "metadata": {"error_type": "payment_required"},
            }
        },
    )
    ok = _response(200, text="{}", json_body={"ok": True})
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(side_effect=[exhausted, ok])

    response = await gateway._request("POST", "/chat/completions", json={"model": "x"})
    assert response.status_code == 200
    assert gateway._client.request.await_count == 2
    auth_headers = [call.kwargs["headers"]["Authorization"] for call in gateway._client.request.await_args_list]
    assert auth_headers == ["Bearer key-a", "Bearer key-b"] or auth_headers == [
        "Bearer key-b",
        "Bearer key-a",
    ]
    assert gateway._pool.status()["keys"][0]["quarantined"] or gateway._pool.status()["keys"][1]["quarantined"]
    assert gateway._pool.in_flight_snapshot() == [0, 0]


@pytest.mark.asyncio
async def test_request_raises_when_all_keys_extra_usage(monkeypatch):
    gateway = _gateway(monkeypatch)
    body = {"error": "extra usage balance is empty, add extra usage"}
    exhausted = _response(402, text='{"error":"extra usage balance is empty, add extra usage"}', json_body=body)
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(return_value=exhausted)

    with pytest.raises(UpstreamServiceError) as exc_info:
        await gateway._request("POST", "/chat/completions", json={"model": "x"})
    assert exc_info.value.status_code == 402
    assert "extra usage" in exc_info.value.user_facing_message().lower()
    assert gateway._pool.all_quarantined()
    assert gateway._pool.in_flight_snapshot() == [0, 0]


@pytest.mark.asyncio
async def test_request_skips_upstream_when_all_already_quarantined(monkeypatch):
    gateway = _gateway(monkeypatch)
    gateway._pool.quarantine(0, "extra usage balance is empty")
    gateway._pool.quarantine(1, "extra usage balance is empty")
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock()

    with pytest.raises(UpstreamServiceError) as exc_info:
        await gateway._request("POST", "/chat/completions", json={"model": "x"})
    assert exc_info.value.status_code == 402
    gateway._client.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_does_not_failover_on_non_extra_usage_402(monkeypatch):
    gateway = _gateway(monkeypatch)
    response = _response(402, text='{"error":"payment required"}', json_body={"error": "payment required"})
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(return_value=response)

    result = await gateway._request("POST", "/chat/completions", json={"model": "x"})
    assert result.status_code == 402
    assert gateway._client.request.await_count == 1
    assert not gateway._pool.status()["keys"][0]["quarantined"]
    assert not gateway._pool.status()["keys"][1]["quarantined"]


@pytest.mark.asyncio
async def test_request_failovers_on_429_session_usage_limit(monkeypatch):
    gateway = _gateway(monkeypatch)
    session_limit = (
        '{"error":{"message":"you (mz038197) have reached your session usage limit, '
        'upgrade for higher limits or add extra usage: https://ollama.com/settings"}}'
    )
    exhausted = _response(429, text=session_limit, json_body={"error": {"message": session_limit}})
    ok = _response(200, text="{}", json_body={"ok": True})
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(side_effect=[exhausted, ok])

    response = await gateway._request("POST", "/chat/completions", json={"model": "gpt-oss:120b-cloud"})
    assert response.status_code == 200
    assert gateway._client.request.await_count == 2
    assert gateway._pool.status()["keys"][0]["quarantined"] or gateway._pool.status()["keys"][1]["quarantined"]


@pytest.mark.asyncio
async def test_request_does_not_failover_on_generic_429(monkeypatch):
    gateway = _gateway(monkeypatch)
    response = _response(
        429,
        text='{"error":{"message":"rate limit exceeded, try again later"}}',
        json_body={"error": {"message": "rate limit exceeded, try again later"}},
    )
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(return_value=response)

    result = await gateway._request("POST", "/chat/completions", json={"model": "x"})
    assert result.status_code == 429
    assert gateway._client.request.await_count == 1
    assert not gateway._pool.status()["keys"][0]["quarantined"]
    assert not gateway._pool.status()["keys"][1]["quarantined"]


@pytest.mark.asyncio
async def test_stream_failovers_on_extra_usage(monkeypatch):
    gateway = _gateway(monkeypatch)

    failed = MagicMock()
    failed.status_code = 402
    failed.aread = AsyncMock(return_value=b'{"error":"extra usage balance is empty"}')
    failed.__aenter__ = AsyncMock(return_value=failed)
    failed.__aexit__ = AsyncMock(return_value=None)

    class _OkStream:
        status_code = 200

        async def aiter_bytes(self):
            yield b"data: ok\n\n"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    gateway._client = MagicMock()
    gateway._client.stream = MagicMock(side_effect=[failed, _OkStream()])

    chunks = []
    async for chunk in gateway._stream("POST", "/responses", json={}):
        chunks.append(chunk)
    assert chunks == [b"data: ok\n\n"]
    assert gateway._client.stream.call_count == 2
    assert gateway._pool.in_flight_snapshot() == [0, 0]


@pytest.mark.asyncio
async def test_stream_failovers_on_credit_exhaustion(monkeypatch):
    gateway = _gateway(monkeypatch)

    failed = MagicMock()
    failed.status_code = 402
    failed.aread = AsyncMock(
        return_value=b'{"error":{"code":402,"message":"Insufficient credits. Add more using https://openrouter.ai/credits"}}'
    )
    failed.__aenter__ = AsyncMock(return_value=failed)
    failed.__aexit__ = AsyncMock(return_value=None)

    class _OkStream:
        status_code = 200

        async def aiter_bytes(self):
            yield b"data: ok\n\n"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    gateway._client = MagicMock()
    gateway._client.stream = MagicMock(side_effect=[failed, _OkStream()])

    chunks = []
    async for chunk in gateway._stream("POST", "/responses", json={}):
        chunks.append(chunk)
    assert chunks == [b"data: ok\n\n"]
    assert gateway._client.stream.call_count == 2
    assert gateway._pool.status()["keys"][0]["quarantined"] or gateway._pool.status()["keys"][1]["quarantined"]
    assert gateway._pool.in_flight_snapshot() == [0, 0]
