import json
from typing import Any, AsyncGenerator

from src.infrastructure.logging.message_preview import build_message_preview, messages_for_log

from src.domain.entities.auth import AuthContext
from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.domain.errors import StatefulResponsesNotSupportedError
from src.domain.ports.api_key_repository import ApiKeyRepositoryPort
from src.domain.ports.llm_gateway import LLMGatewayPort
from src.domain.ports.request_log import RequestLogPort


class ApiUseCase:
    def __init__(
        self,
        gateway: LLMGatewayPort,
        api_key_repo: ApiKeyRepositoryPort,
        logger: RequestLogPort,
    ):
        self.gateway = gateway
        self.api_key_repo = api_key_repo
        self.logger = logger

    async def health(self) -> dict[str, Any]:
        return await self.gateway.health()

    async def models(self) -> dict[str, Any]:
        return await self.gateway.models()

    async def chat_nonstream(
        self,
        req: ChatCompletionRequest,
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        response = await self.gateway.chat_completions_nonstream(req)
        self._log_request(req, api_key, client_ip, auth_context, _usage_from_response(response))
        return response

    async def chat_stream(
        self,
        req: ChatCompletionRequest,
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> AsyncGenerator[bytes, None]:
        usage_tracker = _SseUsageTracker()
        async for chunk in self.gateway.chat_completions_stream(req):
            usage_tracker.feed(chunk)
            yield chunk
        self._log_request(req, api_key, client_ip, auth_context, usage_tracker.usage)

    def validate_responses_request(self, body: dict[str, Any]) -> None:
        self._validate_responses_body(body)

    async def responses_create(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        self._validate_responses_body(body)
        response = await self.gateway.responses_create(body)
        self._log_responses_request(body, api_key, client_ip, auth_context, _usage_from_response(response))
        return response

    async def responses_create_stream(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> AsyncGenerator[bytes, None]:
        self._validate_responses_body(body)
        usage_tracker = _SseUsageTracker()
        async for chunk in self.gateway.responses_create_stream(body):
            usage_tracker.feed(chunk)
            yield chunk
        self._log_responses_request(body, api_key, client_ip, auth_context, usage_tracker.usage)

    def _validate_responses_body(self, body: dict[str, Any]) -> None:
        previous_response_id = body.get("previous_response_id")
        if previous_response_id not in (None, ""):
            raise StatefulResponsesNotSupportedError()

    def _log_responses_request(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None,
        auth_context: AuthContext | None,
        usage: dict[str, int] | None,
    ) -> None:
        model = body.get("model")
        model_name = model if isinstance(model, str) else "N/A"
        messages = _responses_input_for_log(body)
        is_valid, teacher_name, auth_context = self._auth_for_log(api_key, auth_context)
        self.logger.log_validation_result(
            teacher_name=teacher_name,
            api_key=api_key or "未提供",
            model=model_name,
            messages=messages,
            is_valid=is_valid,
            client_ip=client_ip,
        )
        self._log_prompt(auth_context, messages, model_name, "ok" if is_valid else "rejected", client_ip, usage)

    def _log_request(
        self,
        req: ChatCompletionRequest,
        api_key: str | None,
        client_ip: str | None,
        auth_context: AuthContext | None,
        usage: dict[str, int] | None,
    ) -> None:
        is_valid, teacher_name, auth_context = self._auth_for_log(api_key, auth_context)
        messages = [_message_to_log_dict(m) for m in req.messages]
        self.logger.log_validation_result(
            teacher_name=teacher_name,
            api_key=api_key or "未提供",
            model=req.model,
            messages=messages,
            is_valid=is_valid,
            client_ip=client_ip,
        )
        self._log_prompt(auth_context, messages, req.model, "ok" if is_valid else "rejected", client_ip, usage)

    def _auth_for_log(
        self,
        api_key: str | None,
        auth_context: AuthContext | None,
    ) -> tuple[bool, str | None, AuthContext | None]:
        teacher_name: str | None = None
        is_valid = True
        api_key_value = api_key or ""
        if self.api_key_repo.is_enabled():
            if auth_context is None and hasattr(self.api_key_repo, "verify_api_key_context"):
                auth_context = self.api_key_repo.verify_api_key_context(api_key_value)
                is_valid = auth_context is not None
            else:
                is_valid, teacher_name = self.api_key_repo.verify_api_key(api_key_value)
        if auth_context is not None:
            teacher_name = auth_context.teacher_name
        return is_valid, teacher_name, auth_context

    def _log_prompt(
        self,
        auth_context: AuthContext | None,
        messages: list[dict[str, Any]],
        model: str,
        status: str,
        client_ip: str | None,
        usage: dict[str, int] | None,
    ) -> None:
        if not hasattr(self.api_key_repo, "log_prompt"):
            return
        logged_messages = messages_for_log(messages)
        raw_prompt = _messages_to_text(messages)
        self.api_key_repo.log_prompt(
            auth=auth_context,
            raw_prompt=raw_prompt,
            final_prompt=raw_prompt,
            model=model,
            status=status,
            client_ip=client_ip,
            prompt_tokens=int((usage or {}).get("prompt_tokens", 0) or 0),
            completion_tokens=int((usage or {}).get("completion_tokens", 0) or 0),
            total_tokens=int((usage or {}).get("total_tokens", 0) or 0),
            message_preview=build_message_preview(logged_messages),
            messages_json=json.dumps(logged_messages, ensure_ascii=False),
        )

    def log_invalid_auth(self, api_key: str, client_ip: str | None = None) -> None:
        teacher_name: str | None = None
        is_valid = False
        if self.api_key_repo.is_enabled():
            is_valid, teacher_name = self.api_key_repo.verify_api_key(api_key)
        self.logger.log_validation_result(
            teacher_name=teacher_name,
            api_key=api_key or "未提供",
            model="N/A",
            messages=[],
            is_valid=is_valid,
            client_ip=client_ip,
        )


def _message_to_log_dict(m: ChatMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = m.tool_calls
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.tool_name:
        d["tool_name"] = m.tool_name
    return d


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    parts = []
    for message in messages:
        parts.append(f"{message.get('role', '')}: {message.get('content', '')}")
    return "\n".join(parts)


def _extract_usage_raw(payload: dict[str, Any]) -> dict[str, Any] | None:
    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage
    response = payload.get("response")
    if isinstance(response, dict):
        nested = response.get("usage")
        if isinstance(nested, dict):
            return nested
    return None


def _usage_from_raw_usage(usage: dict[str, Any]) -> dict[str, int]:
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _usage_from_response(response: dict[str, Any]) -> dict[str, int]:
    usage = _extract_usage_raw(response)
    if not usage:
        return {}
    return _usage_from_raw_usage(usage)


def _usage_from_sse_event(event: str) -> dict[str, int] | None:
    for line in event.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        usage = _extract_usage_raw(parsed)
        if usage is not None:
            return _usage_from_raw_usage(usage)
    return None


def _merge_usage(current: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    if not new:
        return current
    if not current:
        return new
    if (new.get("total_tokens") or 0) >= (current.get("total_tokens") or 0):
        return new
    return current


class _SseUsageTracker:
    def __init__(self) -> None:
        self._buffer = ""
        self.usage: dict[str, int] = {}

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.decode("utf-8", errors="ignore")
        while "\n\n" in self._buffer:
            event, self._buffer = self._buffer.split("\n\n", 1)
            if not event.strip():
                continue
            found = _usage_from_sse_event(event)
            if found is not None:
                self.usage = _merge_usage(self.usage, found)


def _usage_from_sse_chunk(chunk: bytes) -> dict[str, int] | None:
    tracker = _SseUsageTracker()
    tracker.feed(chunk)
    return tracker.usage or None


def _responses_input_for_log(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = body.get("input")
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []
