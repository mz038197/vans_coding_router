import json
from typing import Any, AsyncGenerator

from src.infrastructure.logging.message_preview import (
    AUDIO_SPEECH_PATH,
    CHAT_COMPLETIONS_PATH,
    IMAGES_PATH,
    RESPONSES_PATH,
    build_message_preview,
    build_response_preview,
    extract_assistant_messages_for_log,
    messages_for_log,
    truncate_assistant_messages,
    truncate_log_text,
)

from src.domain.entities.auth import AuthContext
from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.domain.errors import ImageGenerationDisabledError, StatefulResponsesNotSupportedError, TtsDisabledError
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
        assistant_messages = extract_assistant_messages_for_log(response, CHAT_COMPLETIONS_PATH)
        self._log_request(
            req,
            api_key,
            client_ip,
            auth_context,
            _usage_from_response(response),
            assistant_messages=assistant_messages,
            api_endpoint=CHAT_COMPLETIONS_PATH,
        )
        return response

    async def chat_stream(
        self,
        req: ChatCompletionRequest,
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> AsyncGenerator[bytes, None]:
        tracker = _SseStreamTracker(CHAT_COMPLETIONS_PATH)
        async for chunk in self.gateway.chat_completions_stream(req):
            tracker.feed(chunk)
            yield chunk
        self._log_request(
            req,
            api_key,
            client_ip,
            auth_context,
            tracker.usage,
            assistant_messages=tracker.assistant_messages,
            api_endpoint=CHAT_COMPLETIONS_PATH,
        )

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
        assistant_messages = extract_assistant_messages_for_log(response, RESPONSES_PATH)
        self._log_responses_request(
            body,
            api_key,
            client_ip,
            auth_context,
            _usage_from_response(response),
            assistant_messages=assistant_messages,
            api_endpoint=RESPONSES_PATH,
        )
        return response

    async def responses_create_stream(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> AsyncGenerator[bytes, None]:
        self._validate_responses_body(body)
        tracker = _SseStreamTracker(RESPONSES_PATH)
        async for chunk in self.gateway.responses_create_stream(body):
            tracker.feed(chunk)
            yield chunk
        self._log_responses_request(
            body,
            api_key,
            client_ip,
            auth_context,
            tracker.usage,
            assistant_messages=tracker.assistant_messages,
            api_endpoint=RESPONSES_PATH,
        )

    async def images_create(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        self._assert_image_generation_allowed(auth_context)
        response = await self.gateway.images_create(body)
        self._log_images_request(
            body,
            api_key,
            client_ip,
            auth_context,
            _usage_from_response(response),
            response,
            api_endpoint=IMAGES_PATH,
        )
        return response

    async def images_create_stream(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> AsyncGenerator[bytes, None]:
        self._assert_image_generation_allowed(auth_context)
        tracker = _ImageSseStreamTracker()
        async for chunk in self.gateway.images_create_stream(body):
            tracker.feed(chunk)
            yield chunk
        self._log_images_request(
            body,
            api_key,
            client_ip,
            auth_context,
            tracker.usage,
            tracker.last_response,
            api_endpoint=IMAGES_PATH,
        )

    async def images_models(
        self,
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
        self._assert_image_generation_allowed(auth_context)
        return await self.gateway.images_models()

    async def audio_speech_stream(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None = None,
        auth_context: AuthContext | None = None,
    ) -> AsyncGenerator[bytes, None]:
        byte_count = 0
        async for chunk in self.gateway.audio_speech_create_stream(body):
            byte_count += len(chunk)
            yield chunk
        self._log_tts_request(
            body,
            api_key,
            client_ip,
            auth_context,
            byte_count,
            api_endpoint=AUDIO_SPEECH_PATH,
        )

    def _assert_image_generation_allowed(self, auth_context: AuthContext | None) -> None:
        if auth_context is None or auth_context.session_id is None:
            return
        if not hasattr(self.api_key_repo, "is_image_generation_enabled"):
            return
        if not self.api_key_repo.is_image_generation_enabled(auth_context.session_id):
            raise ImageGenerationDisabledError()

    def _assert_tts_allowed(self, auth_context: AuthContext | None) -> None:
        if auth_context is None or auth_context.session_id is None:
            return
        if not hasattr(self.api_key_repo, "is_tts_enabled"):
            return
        if not self.api_key_repo.is_tts_enabled(auth_context.session_id):
            raise TtsDisabledError()

    def validate_audio_speech_request(
        self,
        body: dict[str, Any],
        auth_context: AuthContext | None = None,
    ) -> None:
        self._assert_tts_allowed(auth_context)
        self._prepare_audio_speech_body(body)

    def _prepare_audio_speech_body(self, body: dict[str, Any]) -> None:
        prepare = getattr(self.gateway, "prepare_audio_speech_body", None)
        if callable(prepare):
            prepare(body)

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
        assistant_messages: list[dict[str, Any]] | None = None,
        api_endpoint: str = RESPONSES_PATH,
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
        self._log_prompt(
            auth_context,
            messages,
            model_name,
            "ok" if is_valid else "rejected",
            client_ip,
            usage,
            assistant_messages=assistant_messages,
            api_endpoint=api_endpoint,
        )

    def _log_request(
        self,
        req: ChatCompletionRequest,
        api_key: str | None,
        client_ip: str | None,
        auth_context: AuthContext | None,
        usage: dict[str, int] | None,
        assistant_messages: list[dict[str, Any]] | None = None,
        api_endpoint: str = CHAT_COMPLETIONS_PATH,
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
        self._log_prompt(
            auth_context,
            messages,
            req.model,
            "ok" if is_valid else "rejected",
            client_ip,
            usage,
            assistant_messages=assistant_messages,
            api_endpoint=api_endpoint,
        )

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
        assistant_messages: list[dict[str, Any]] | None = None,
        api_endpoint: str = "",
    ) -> None:
        if not hasattr(self.api_key_repo, "log_prompt"):
            return
        logged_request = messages_for_log(messages)
        logged_assistant = truncate_assistant_messages(messages_for_log(assistant_messages or []))
        logged_messages = logged_request + logged_assistant
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
            message_preview=build_message_preview(logged_request),
            response_preview=build_response_preview(logged_messages),
            messages_json=json.dumps(logged_messages, ensure_ascii=False),
            api_endpoint=api_endpoint,
        )

    def _log_images_request(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None,
        auth_context: AuthContext | None,
        usage: dict[str, int] | None,
        response: dict[str, Any] | None,
        api_endpoint: str = IMAGES_PATH,
    ) -> None:
        model = body.get("model")
        model_name = model if isinstance(model, str) else "N/A"
        prompt = body.get("prompt")
        prompt_text = prompt if isinstance(prompt, str) else ""
        messages = [{"role": "user", "content": prompt_text}] if prompt_text else []
        image_count = _image_count_from_response(response)
        assistant_messages = (
            [{"role": "assistant", "content": f"[image: {image_count} generated]"}]
            if image_count
            else []
        )
        is_valid, teacher_name, auth_context = self._auth_for_log(api_key, auth_context)
        self.logger.log_validation_result(
            teacher_name=teacher_name,
            api_key=api_key or "未提供",
            model=model_name,
            messages=messages,
            is_valid=is_valid,
            client_ip=client_ip,
        )
        self._log_prompt(
            auth_context,
            messages,
            model_name,
            "ok" if is_valid else "rejected",
            client_ip,
            usage,
            assistant_messages=assistant_messages,
            api_endpoint=api_endpoint,
        )

    def _log_tts_request(
        self,
        body: dict[str, Any],
        api_key: str | None,
        client_ip: str | None,
        auth_context: AuthContext | None,
        byte_count: int,
        api_endpoint: str = AUDIO_SPEECH_PATH,
    ) -> None:
        model = body.get("model")
        model_name = model if isinstance(model, str) else "N/A"
        text_input = body.get("input")
        input_text = text_input if isinstance(text_input, str) else ""
        messages = [{"role": "user", "content": input_text}] if input_text else []
        assistant_messages = (
            [{"role": "assistant", "content": f"[audio: {byte_count} bytes streamed]"}]
            if byte_count
            else []
        )
        is_valid, teacher_name, auth_context = self._auth_for_log(api_key, auth_context)
        self.logger.log_validation_result(
            teacher_name=teacher_name,
            api_key=api_key or "未提供",
            model=model_name,
            messages=messages,
            is_valid=is_valid,
            client_ip=client_ip,
        )
        self._log_prompt(
            auth_context,
            messages,
            model_name,
            "ok" if is_valid else "rejected",
            client_ip,
            None,
            assistant_messages=assistant_messages,
            api_endpoint=api_endpoint,
        )

    def log_invalid_auth(self, api_key: str, client_ip: str | None = None) -> None:
        from src.infrastructure.auth.client_api_key import normalize_api_key
        from src.presentation.fastapi.auth_errors import resolve_auth_error

        api_key = normalize_api_key(api_key)
        teacher_name: str | None = None
        is_valid = False
        if self.api_key_repo.is_enabled():
            auth_err = resolve_auth_error(api_key, self.api_key_repo)
            if auth_err is None:
                context = self.api_key_repo.verify_api_key_context(api_key)
                is_valid = context is not None
                if context is not None:
                    teacher_name = context.teacher_name
        self.logger.log_validation_result(
            teacher_name=teacher_name,
            api_key=(api_key[:14] + "...") if len(api_key) > 14 else (api_key or "未提供"),
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


def _payload_from_sse_event(event: str) -> dict[str, Any] | None:
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
        if isinstance(parsed, dict):
            return parsed
    return None


def _usage_from_sse_event(event: str) -> dict[str, int] | None:
    parsed = _payload_from_sse_event(event)
    if not parsed:
        return None
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


def _assistant_text_from_sse_payload(payload: dict[str, Any], api_endpoint: str) -> str | None:
    if api_endpoint == RESPONSES_PATH:
        messages = extract_assistant_messages_for_log(payload, RESPONSES_PATH)
        if messages:
            content = messages[0].get("content")
            return content if isinstance(content, str) else None
        nested = payload.get("response")
        if isinstance(nested, dict):
            messages = extract_assistant_messages_for_log(nested, RESPONSES_PATH)
            if messages:
                content = messages[0].get("content")
                return content if isinstance(content, str) else None
        return None

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str) and content:
            return content
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content:
            return content
    return None


class _SseStreamTracker:
    def __init__(self, api_endpoint: str) -> None:
        self.api_endpoint = api_endpoint
        self._buffer = ""
        self.usage: dict[str, int] = {}
        self._assistant_parts: list[str] = []
        self._responses_completed = False

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.decode("utf-8", errors="ignore")
        while "\n\n" in self._buffer:
            event, self._buffer = self._buffer.split("\n\n", 1)
            if not event.strip():
                continue
            found = _usage_from_sse_event(event)
            if found is not None:
                self.usage = _merge_usage(self.usage, found)
            payload = _payload_from_sse_event(event)
            if payload is not None:
                self._feed_payload(payload)

    def _feed_payload(self, payload: dict[str, Any]) -> None:
        if self.api_endpoint == RESPONSES_PATH and payload.get("type") == "response.completed":
            self._responses_completed = True
            self._assistant_parts = []
            text = _assistant_text_from_sse_payload(payload, self.api_endpoint)
            if text:
                self._assistant_parts.append(text)
            return

        if self._responses_completed:
            return

        text = _assistant_text_from_sse_payload(payload, self.api_endpoint)
        if text:
            self._assistant_parts.append(text)

    @property
    def assistant_messages(self) -> list[dict[str, Any]]:
        if not self._assistant_parts:
            return []
        combined, _ = truncate_log_text("".join(self._assistant_parts))
        if not combined:
            return []
        return [{"role": "assistant", "content": combined}]


class _SseUsageTracker(_SseStreamTracker):
    """Backward-compatible alias for tests that only track usage."""

    def __init__(self) -> None:
        super().__init__(CHAT_COMPLETIONS_PATH)


class _ImageSseStreamTracker:
    def __init__(self) -> None:
        self._buffer = ""
        self.usage: dict[str, int] = {}
        self.last_response: dict[str, Any] | None = None

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.decode("utf-8", errors="ignore")
        while "\n\n" in self._buffer:
            event, self._buffer = self._buffer.split("\n\n", 1)
            if not event.strip():
                continue
            found = _usage_from_sse_event(event)
            if found is not None:
                self.usage = _merge_usage(self.usage, found)
            payload = _payload_from_sse_event(event)
            if payload is not None:
                event_type = payload.get("type")
                if event_type == "image_generation.completed" or "data" in payload:
                    self.last_response = payload


def _image_count_from_response(response: dict[str, Any] | None) -> int:
    if not response:
        return 0
    data = response.get("data")
    if isinstance(data, list):
        return len(data)
    if response.get("type") == "image_generation.completed" and response.get("b64_json"):
        return 1
    return 0


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
