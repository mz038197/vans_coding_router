from dataclasses import dataclass
from typing import Any


@dataclass
class ChatMessage:
    role: str
    content: str = ""
    images: list[str] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    name: str | None = None


@dataclass
class ChatCompletionRequest:
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = 0.7
    max_tokens: int | None = 200000
    user: str | None = None
    stop: object | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None


@dataclass
class AddTeacherInput:
    name: str


@dataclass
class DeleteTeacherInput:
    teacher: str


@dataclass
class AddKeyInput:
    teacher: str
    name: str
    key: str
    enabled: bool = True


@dataclass
class UpdateKeyStatusInput:
    teacher: str
    key: str
    enabled: bool = True


@dataclass
class DeleteKeyInput:
    teacher: str
    key: str
