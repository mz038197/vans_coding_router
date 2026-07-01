from typing import Any, AsyncGenerator

import pytest

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.domain.errors import InvalidModelIdError, TtsNotSupportedError
from src.infrastructure.config import CAPABILITY_AUDIO_SPEECH, ProviderSettings
from src.infrastructure.gateways.routing_gateway import RoutingGateway


class FakeGateway:
    def __init__(self, name: str, capabilities: tuple[str, ...] = ()):
        self.name = name
        self.provider = ProviderSettings(name=name, capabilities=capabilities)
        self.requests: list[str] = []
        self.last_chat_req: ChatCompletionRequest | None = None

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def models(self) -> dict[str, Any]:
        if self.name == "openrouter":
            return {"object": "list", "data": [{"id": "anthropic/claude-sonnet", "object": "model"}]}
        return {"object": "list", "data": [{"id": "qwen3-coder-next", "object": "model"}]}

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        self.requests.append(req.model)
        self.last_chat_req = req
        return {"provider": self.name}

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        self.requests.append(req.model)
        self.last_chat_req = req
        yield b"data: [DONE]\n\n"

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(str(body.get("model")))
        return {"provider": self.name}

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        self.requests.append(str(body.get("model")))
        yield b"data: [DONE]\n\n"

    async def images_create(self, body: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(str(body.get("model")))
        return {"provider": self.name}

    async def images_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        self.requests.append(str(body.get("model")))
        yield b"data: [DONE]\n\n"

    async def images_models(self) -> dict[str, Any]:
        return {"object": "list", "data": [{"id": "flux.2-pro"}]}

    async def audio_speech_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        self.requests.append(str(body.get("model")))
        yield b"\x00\x01"


@pytest.fixture
def gateway() -> RoutingGateway:
    return RoutingGateway(
        {
            "openrouter": FakeGateway("openrouter"),
            "ollama_cloud": FakeGateway("ollama_cloud"),
        }
    )


@pytest.fixture
def audio_gateway() -> RoutingGateway:
    return RoutingGateway(
        {
            "openrouter": FakeGateway("openrouter"),
            "ollama_cloud": FakeGateway("ollama_cloud"),
            "openai": FakeGateway("openai", (CAPABILITY_AUDIO_SPEECH,)),
        }
    )


@pytest.mark.asyncio
async def test_routing_gateway_routes_openrouter_at_model(gateway: RoutingGateway):
    openrouter = gateway.gateways["openrouter"]
    ollama_cloud = gateway.gateways["ollama_cloud"]

    response = await gateway.chat_completions_nonstream(
        ChatCompletionRequest(
            model="openrouter@anthropic/claude-sonnet",
            messages=[ChatMessage(role="user", content="hi")],
        )
    )

    assert response == {"provider": "openrouter"}
    assert openrouter.requests == ["anthropic/claude-sonnet"]
    assert ollama_cloud.requests == []


@pytest.mark.asyncio
async def test_routing_gateway_routes_openrouter_slug_with_colon_suffix(gateway: RoutingGateway):
    openrouter = gateway.gateways["openrouter"]

    await gateway.responses_create({"model": "openrouter@openai/gpt-oss-120b:free", "input": "hi"})

    assert openrouter.requests == ["openai/gpt-oss-120b:free"]


@pytest.mark.asyncio
async def test_routing_gateway_routes_ollama_at_model(gateway: RoutingGateway):
    ollama_cloud = gateway.gateways["ollama_cloud"]

    response = await gateway.responses_create({"model": "ollama_cloud@qwen3-coder-next", "input": "hi"})

    assert response == {"provider": "ollama_cloud"}
    assert ollama_cloud.requests == ["qwen3-coder-next:cloud"]


@pytest.mark.asyncio
async def test_routing_gateway_ollama_responses_adds_cloud_suffix(gateway: RoutingGateway):
    ollama_cloud = gateway.gateways["ollama_cloud"]

    await gateway.responses_create({"model": "ollama_cloud@minimax-m3", "input": "hi"})

    assert ollama_cloud.requests == ["minimax-m3:cloud"]


@pytest.mark.asyncio
async def test_routing_gateway_ollama_tagged_model_uses_dash_cloud(gateway: RoutingGateway):
    ollama = gateway.gateways["ollama_cloud"]

    await gateway.responses_create({"model": "ollama_cloud@gpt-oss:20b", "input": "hi"})

    assert ollama.requests == ["gpt-oss:20b-cloud"]


@pytest.mark.asyncio
async def test_routing_gateway_ollama_cloud_suffix_idempotent(gateway: RoutingGateway):
    ollama_cloud = gateway.gateways["ollama_cloud"]

    await gateway.responses_create({"model": "ollama_cloud@minimax-m3:cloud", "input": "hi"})

    assert ollama_cloud.requests == ["minimax-m3:cloud"]


@pytest.mark.asyncio
async def test_routing_gateway_rejects_bare_model(gateway: RoutingGateway):
    with pytest.raises(InvalidModelIdError):
        await gateway.responses_create({"model": "qwen3-coder-next", "input": "hi"})


@pytest.mark.asyncio
async def test_routing_gateway_models_return_prefixed_ids(gateway: RoutingGateway):
    models = await gateway.models()

    assert models["object"] == "list"
    ids = {item["id"] for item in models["data"]}
    assert ids == {"openrouter@anthropic/claude-sonnet", "ollama_cloud@qwen3-coder-next:cloud"}
    assert {item["provider"] for item in models["data"]} == {"openrouter", "ollama_cloud"}


@pytest.mark.asyncio
async def test_routing_gateway_images_create_strips_provider_prefix(gateway: RoutingGateway):
    openrouter = gateway.gateways["openrouter"]

    response = await gateway.images_create(
        {"model": "openrouter@black-forest-labs/flux.2-pro", "prompt": "cat"}
    )

    assert response == {"provider": "openrouter"}
    assert openrouter.requests == ["black-forest-labs/flux.2-pro"]


@pytest.mark.asyncio
async def test_routing_gateway_images_models_prefix_ids(gateway: RoutingGateway):
    models = await gateway.images_models()

    assert models["data"][0]["id"] == "openrouter@flux.2-pro"
    assert models["data"][0]["provider"] == "openrouter"


@pytest.mark.asyncio
async def test_routing_gateway_audio_speech_strips_provider_prefix(audio_gateway: RoutingGateway):
    openai = audio_gateway.gateways["openai"]

    chunks = []
    async for chunk in audio_gateway.audio_speech_create_stream(
        {
            "model": "openai@gpt-4o-mini-tts",
            "input": "hello",
            "voice": "nova",
            "response_format": "pcm",
        }
    ):
        chunks.append(chunk)

    assert chunks == [b"\x00\x01"]
    assert openai.requests == ["gpt-4o-mini-tts"]


@pytest.mark.asyncio
async def test_routing_gateway_audio_speech_rejects_unsupported_provider(audio_gateway: RoutingGateway):
    with pytest.raises(TtsNotSupportedError):
        async for _chunk in audio_gateway.audio_speech_create_stream(
            {"model": "openrouter@gpt-4o-mini-tts", "input": "hello", "voice": "nova"}
        ):
            pass
