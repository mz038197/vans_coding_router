from __future__ import annotations

from fnmatch import fnmatch
from typing import Any, AsyncGenerator

from src.domain.entities.chat import ChatCompletionRequest
from src.domain.errors import ServiceUnavailableError
from src.domain.ports.llm_gateway import LLMGatewayPort
from src.infrastructure.config import RoutingSettings


class RoutingGateway:
    def __init__(self, gateways: dict[str, LLMGatewayPort], routing: RoutingSettings):
        self.gateways = gateways
        self.routing = routing

    async def startup(self) -> None:
        for gateway in self.gateways.values():
            await gateway.startup()

    async def shutdown(self) -> None:
        for gateway in self.gateways.values():
            await gateway.shutdown()

    async def health(self) -> dict[str, Any]:
        providers: dict[str, Any] = {}
        for name, gateway in self.gateways.items():
            providers[name] = await gateway.health()
        return {"ok": all(item.get("ok") for item in providers.values()), "providers": providers}

    async def models(self) -> dict[str, Any]:
        data: list[dict[str, Any]] = []
        errors: dict[str, Any] = {}
        for name, gateway in self.gateways.items():
            try:
                models = await gateway.models()
                for item in models.get("data", []):
                    if isinstance(item, dict):
                        data.append({"provider": name, **item})
            except Exception as exc:
                errors[name] = str(exc)
        result: dict[str, Any] = {"object": "list", "data": data}
        if errors:
            result["provider_errors"] = errors
        return result

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        return await self._gateway_for_model(req.model).chat_completions_nonstream(req)

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        async for chunk in self._gateway_for_model(req.model).chat_completions_stream(req):
            yield chunk

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._gateway_for_model(str(body.get("model", ""))).responses_create(body)

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        async for chunk in self._gateway_for_model(str(body.get("model", ""))).responses_create_stream(body):
            yield chunk

    def _gateway_for_model(self, model: str) -> LLMGatewayPort:
        provider_name = self._provider_for_model(model)
        gateway = self.gateways.get(provider_name)
        if gateway is None:
            raise ServiceUnavailableError(f"No provider configured for model '{model}'")
        return gateway

    def _provider_for_model(self, model: str) -> str:
        for rule in self.routing.rules:
            if rule.match and fnmatch(model, rule.match):
                return rule.provider
        if self.routing.default_provider:
            return self.routing.default_provider
        if self.gateways:
            return next(iter(self.gateways))
        raise ServiceUnavailableError("No LLM providers configured")
