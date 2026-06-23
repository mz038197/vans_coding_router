from typing import Any, AsyncGenerator, Protocol

from src.domain.entities.chat import ChatCompletionRequest


class LLMGatewayPort(Protocol):
    async def startup(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...

    async def models(self) -> dict[str, Any]:
        ...

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        ...

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        ...

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        ...

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        ...

    async def images_create(self, body: dict[str, Any]) -> dict[str, Any]:
        ...

    async def images_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        ...

    async def images_models(self) -> dict[str, Any]:
        ...

    async def audio_speech_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        ...
