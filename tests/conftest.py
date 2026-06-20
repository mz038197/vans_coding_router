from collections.abc import AsyncGenerator
from pathlib import Path
import sys
import uuid
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.infrastructure.logging.file_request_logger import _build_message_preview


class FakeApiKeyRepository:
    def __init__(self, config_data: dict[str, Any] | None = None, force_enabled: bool | None = None):
        self.config_data = config_data or {}
        self.force_enabled = force_enabled

    def verify_api_key(self, api_key: str) -> tuple[bool, str | None]:
        if not api_key:
            return False, None
        for teacher_name, teacher_data in self.config_data.items():
            for key_info in teacher_data.get("api_keys", []):
                if key_info["key"] == api_key and key_info.get("enabled", False):
                    return True, teacher_name
        return False, None

    def is_enabled(self) -> bool:
        if self.force_enabled is not None:
            return self.force_enabled
        return bool(self.config_data)

    def get_all_config(self) -> dict[str, Any]:
        return self.config_data

    def add_teacher(self, teacher_name: str) -> None:
        if teacher_name not in self.config_data:
            self.config_data[teacher_name] = {"api_keys": []}

    def delete_teacher(self, teacher_name: str) -> bool:
        if teacher_name not in self.config_data:
            return False
        del self.config_data[teacher_name]
        return True

    def add_api_key(self, teacher_name: str, name: str, key: str, enabled: bool = True) -> None:
        self.add_teacher(teacher_name)
        self.config_data[teacher_name]["api_keys"].append(
            {"name": name, "key": key, "enabled": enabled}
        )

    def update_api_key(
        self,
        teacher_name: str,
        old_key: str,
        name: str,
        key: str,
        enabled: bool,
    ) -> bool:
        if teacher_name not in self.config_data:
            return False
        api_keys = self.config_data[teacher_name].get("api_keys", [])
        for key_info in api_keys:
            if key_info["key"] == old_key:
                key_info["name"] = name
                key_info["key"] = key
                key_info["enabled"] = enabled
                return True
        return False

    def update_api_key_status(self, teacher_name: str, key: str, enabled: bool) -> bool:
        if teacher_name not in self.config_data:
            return False
        for key_info in self.config_data[teacher_name].get("api_keys", []):
            if key_info["key"] == key:
                key_info["enabled"] = enabled
                return True
        return False

    def delete_api_key(self, teacher_name: str, key: str) -> bool:
        if teacher_name not in self.config_data:
            return False
        api_keys = self.config_data[teacher_name].get("api_keys", [])
        for idx, key_info in enumerate(api_keys):
            if key_info["key"] == key:
                api_keys.pop(idx)
                return True
        return False


class FakeRequestLogger:
    def __init__(self):
        self.entries: list[dict[str, Any]] = []

    def log_validation_result(
        self,
        teacher_name: str | None,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        is_valid: bool,
        client_ip: str | None = None,
    ) -> None:
        request_id = str(uuid.uuid4())
        self.entries.append(
            {
                "request_id": request_id,
                "teacher_name": teacher_name,
                "api_key": api_key,
                "model": model,
                "messages": messages,
                "is_valid": is_valid,
                "client_ip": client_ip or "unknown",
                "message_preview": _build_message_preview(messages),
            }
        )

    def get_log_detail(self, request_id: str, date: str | None = None) -> dict[str, Any] | None:
        for entry in self.entries:
            if entry.get("request_id") == request_id:
                return {
                    "request_id": entry["request_id"],
                    "timestamp": "2026-03-13 00:00:00",
                    "client_ip": entry.get("client_ip", "unknown"),
                    "teacher": entry.get("teacher_name") or "未知",
                    "api_key": entry.get("api_key", ""),
                    "model": entry.get("model", ""),
                    "is_valid": entry.get("is_valid", False),
                    "validation_result": "通過" if entry.get("is_valid") else "拒絕",
                    "messages": entry.get("messages") or [],
                }
        return None

    def query_logs(
        self,
        date: str | None = None,
        teacher: str | None = None,
        model: str | None = None,
        is_valid: bool | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        matched = []
        keyword_filter = keyword.strip().lower() if keyword else None
        for entry in self.entries:
            message_preview = entry.get("message_preview", "")
            messages = entry.get("messages") or []

            if teacher and entry.get("teacher_name") != teacher:
                continue
            if model and entry.get("model") != model:
                continue
            if is_valid is not None and bool(entry.get("is_valid")) is not is_valid:
                continue
            if keyword_filter and keyword_filter not in "\n".join(
                [message_preview] + [str(msg.get("content", "")) for msg in messages]
            ).lower():
                continue

            matched.append(
                {
                    "request_id": entry.get("request_id"),
                    "timestamp": "2026-03-13 00:00:00",
                    "client_ip": entry.get("client_ip", "unknown"),
                    "teacher": entry.get("teacher_name") or "未知",
                    "api_key": entry.get("api_key", ""),
                    "model": entry.get("model", ""),
                    "is_valid": entry.get("is_valid", False),
                    "validation_result": "通過" if entry.get("is_valid") else "拒絕",
                    "message_preview": message_preview,
                }
            )

        matched.reverse()
        start = max(offset, 0)
        end = start + max(limit, 1)
        items = matched[start:end]
        return {"items": items, "total": len(matched), "has_more": end < len(matched)}


class FakeLLMGateway:
    def __init__(self):
        self.last_nonstream_req: ChatCompletionRequest | None = None
        self.last_stream_req: ChatCompletionRequest | None = None
        self.health_response = {"queue_waiting": 0, "backends": []}
        self.models_response = {"object": "list", "data": [{"id": "fake-model", "object": "model", "owned_by": "ollama"}]}
        self.nonstream_response = {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 123,
            "model": "fake-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        self.stream_chunks = [
            b'data: {"id":"chatcmpl-fake","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n',
            b"data: [DONE]\n\n",
        ]
        self.last_responses_body: dict[str, Any] | None = None
        self.responses_response = {
            "id": "resp_fake",
            "object": "response",
            "status": "completed",
            "output": [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hello"}]},
            ],
        }
        self.responses_stream_chunks = [
            b'event: response.created\ndata: {"type":"response.created"}\n\n',
            b'event: response.completed\ndata: {"type":"response.completed"}\n\n',
        ]

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def health(self) -> dict[str, Any]:
        return self.health_response

    async def models(self) -> dict[str, Any]:
        return self.models_response

    async def chat_completions_nonstream(self, req: ChatCompletionRequest) -> dict[str, Any]:
        self.last_nonstream_req = req
        return self.nonstream_response

    async def chat_completions_stream(
        self, req: ChatCompletionRequest
    ) -> AsyncGenerator[bytes, None]:
        self.last_stream_req = req
        for chunk in self.stream_chunks:
            yield chunk

    async def responses_create(self, body: dict[str, Any]) -> dict[str, Any]:
        self.last_responses_body = body
        return self.responses_response

    async def responses_create_stream(
        self, body: dict[str, Any]
    ) -> AsyncGenerator[bytes, None]:
        self.last_responses_body = body
        for chunk in self.responses_stream_chunks:
            yield chunk


@pytest.fixture
def fake_repo() -> FakeApiKeyRepository:
    return FakeApiKeyRepository(
        config_data={
            "TeacherA": {
                "api_keys": [
                    {"name": "ClassA", "key": "valid-key", "enabled": True},
                    {"name": "ClassB", "key": "disabled-key", "enabled": False},
                ]
            }
        },
        force_enabled=True,
    )


@pytest.fixture
def fake_logger() -> FakeRequestLogger:
    return FakeRequestLogger()


@pytest.fixture
def fake_gateway() -> FakeLLMGateway:
    return FakeLLMGateway()


@pytest.fixture
def sample_chat_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="fake-model",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
        temperature=0.7,
        max_tokens=16,
    )
