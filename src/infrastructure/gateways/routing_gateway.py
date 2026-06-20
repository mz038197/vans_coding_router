from __future__ import annotations

from dataclasses import replace
from typing import Any, AsyncGenerator

from src.domain.entities.chat import ChatCompletionRequest
from src.domain.ports.llm_gateway import LLMGatewayPort
from src.infrastructure.routing.model_id import format_model_id, parse_model_id


class RoutingGateway:
    def __init__(self, gateways: dict[str, LLMGatewayPort]):
        self.gateways = gateways

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
                    if not isinstance(item, dict):
                        continue
                    upstream_id = str(item.get("id", ""))
                    if not upstream_id:
                        continue
                    entry = dict(item)
                    entry["id"] = format_model_id(name, upstream_id)
                    entry["provider"] = name
                    data.append(entry)
            except Exception as exc:
                errors[name] = str(exc)
        result: dict[str, Any] = {"object": "list", "data": data}
        if errors:
            result["provider_errors"] = errors
        return result

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        gateway, upstream_req = self._resolve_chat_request(req)
        return await gateway.chat_completions_nonstream(upstream_req)

    async def chat_completions_stream(self, req: ChatCompletionRequest) -> AsyncGenerator[bytes, None]:
        gateway, upstream_req = self._resolve_chat_request(req)
        async for chunk in gateway.chat_completions_stream(upstream_req):
            yield chunk

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        gateway, payload = self._resolve_responses_body(body)
        return await gateway.responses_create(payload)

    async def responses_create_stream(self, body: dict[str, Any]) -> AsyncGenerator[bytes, None]:
        gateway, payload = self._resolve_responses_body(body)
        async for chunk in gateway.responses_create_stream(payload):
            yield chunk

    def _known_providers(self) -> set[str]:
        return set(self.gateways.keys())

    def _resolve_chat_request(self, req: ChatCompletionRequest) -> tuple[LLMGatewayPort, ChatCompletionRequest]:
        provider_name, upstream_model = parse_model_id(req.model, self._known_providers())
        gateway = self.gateways[provider_name]
        return gateway, replace(req, model=upstream_model)

    def _resolve_responses_body(self, body: dict[str, Any]) -> tuple[LLMGatewayPort, dict[str, Any]]:
        provider_name, upstream_model = parse_model_id(str(body.get("model", "")), self._known_providers())
        payload = dict(body)
        payload["model"] = upstream_model
        return self.gateways[provider_name], payload
