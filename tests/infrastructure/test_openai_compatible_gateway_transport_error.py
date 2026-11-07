"""Model lists tell an unreachable upstream apart from a missing base_url."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.domain.errors import ServiceUnavailableError, UpstreamTransportError
from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway


def _gateway(monkeypatch, base_url: str) -> OpenAICompatibleGateway:
    monkeypatch.setenv("TRANSPORT_KEY", "secret")
    return OpenAICompatibleGateway(
        ProviderSettings(
            name="openai",
            type="openai_compatible",
            base_url=base_url,
            api_key_env="TRANSPORT_KEY",
        ),
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_models_raises_a_transport_error_when_the_upstream_is_unreachable(monkeypatch):
    gateway = _gateway(monkeypatch, "https://example.test/v1")
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(UpstreamTransportError, match="openai unavailable: boom"):
        await gateway.models()


@pytest.mark.asyncio
async def test_models_without_a_base_url_is_not_a_transport_error(monkeypatch):
    gateway = _gateway(monkeypatch, "")
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(side_effect=httpx.UnsupportedProtocol("no scheme"))

    with pytest.raises(ServiceUnavailableError, match="openai unavailable: missing base_url") as raised:
        await gateway.models()

    assert not isinstance(raised.value, UpstreamTransportError)
    gateway._client.request.assert_not_called()
