from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str
    content: str | list[Any] = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    name: str | None = None
    # 客戶端在這則訊息上送的其他欄位，原樣轉發。
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatCompletionRequest:
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    # 客戶端送的其他頂層欄位，原樣轉發。
    extra: dict[str, Any] = field(default_factory=dict)


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
