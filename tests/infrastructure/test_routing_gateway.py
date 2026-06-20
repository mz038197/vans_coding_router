from typing import Any, AsyncGenerator

import pytest

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.infrastructure.config import RoutingRuleSettings, RoutingSettings
from src.infrastructure.gateways.routing_gateway import RoutingGateway


class FakeGateway:
    def __init__(self, name: str):
        self.name = name
        self.requests: list[str] = []

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def models(self) -> dict[str, Any]:
        return {"object": "list", "data": [{"id": f"{self.name}-model", "object": "model"}]}

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        self.requests.append(req.model)
        return {"provider": self.name}

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        self.requests.append(req.model)
        yield b"data: [DONE]\n\n"

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(str(body.get("model")))
        return {"provider": self.name}

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        self.requests.append(str(body.get("model")))
        yield b"data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_routing_gateway_uses_matching_rule():
    openrouter = FakeGateway("openrouter")
    ollama_cloud = FakeGateway("ollama_cloud")
    gateway = RoutingGateway(
        {"openrouter": openrouter, "ollama_cloud": ollama_cloud},
        RoutingSettings(
            default_provider="ollama_cloud",
            rules=(RoutingRuleSettings(match="anthropic/*", provider="openrouter"),),
        ),
    )

    response = await gateway.chat_completions_nonstream(
        ChatCompletionRequest(model="anthropic/claude-sonnet", messages=[ChatMessage(role="user", content="hi")])
    )

    assert response == {"provider": "openrouter"}
    assert openrouter.requests == ["anthropic/claude-sonnet"]
    assert ollama_cloud.requests == []


@pytest.mark.asyncio
async def test_routing_gateway_falls_back_to_default_provider():
    openrouter = FakeGateway("openrouter")
    ollama_cloud = FakeGateway("ollama_cloud")
    gateway = RoutingGateway(
        {"openrouter": openrouter, "ollama_cloud": ollama_cloud},
        RoutingSettings(default_provider="ollama_cloud"),
    )

    response = await gateway.responses_create({"model": "llama3.3"})

    assert response == {"provider": "ollama_cloud"}
    assert ollama_cloud.requests == ["llama3.3"]


@pytest.mark.asyncio
async def test_routing_gateway_merges_models_with_provider_name():
    gateway = RoutingGateway(
        {"openrouter": FakeGateway("openrouter"), "ollama_cloud": FakeGateway("ollama_cloud")},
        RoutingSettings(default_provider="ollama_cloud"),
    )

    models = await gateway.models()

    assert models["object"] == "list"
    assert {item["provider"] for item in models["data"]} == {"openrouter", "ollama_cloud"}
