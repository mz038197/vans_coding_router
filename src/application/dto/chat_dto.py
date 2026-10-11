from dataclasses import dataclass
from typing import Any

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage


# 純 base64 沒有 MIME 類型，從開頭位元組的 base64 前綴判斷。
_BASE64_IMAGE_TYPES = (("/9j/", "jpeg"), ("iVBOR", "png"), ("R0lGOD", "gif"), ("UklGR", "webp"))


def _older_image_part(value: Any) -> dict[str, Any] | None:
    """舊客戶端 images 欄位的一個值（純 base64、data URL 或網址）轉成 image_url 區塊。"""
    if not isinstance(value, str) or not value:
        return None
    if not value.startswith(("data:", "http://", "https://")):
        kind = next((kind for prefix, kind in _BASE64_IMAGE_TYPES if value.startswith(prefix)), "jpeg")
        value = f"data:image/{kind};base64,{value}"
    return {"type": "image_url", "image_url": {"url": value}}


def _upstream_content(content: Any, older_images: Any = None) -> str | list[Any]:
    """上游都是 OpenAI 相容格式，content 原樣轉發，不拆解也不改寫。"""
    if not isinstance(content, (str, list)):
        content = ""
    image_parts = [part for part in map(_older_image_part, older_images or []) if part]
    if not image_parts:
        return content
    if isinstance(content, str):
        content = [{"type": "text", "text": content}] if content else []
    return [*content, *image_parts]


_MESSAGE_FIELDS = frozenset({"role", "content", "images", "tool_calls", "tool_call_id", "tool_name", "name"})


@dataclass
class ChatCompletionInputDto:
    model: str
    messages: list[dict[str, Any]]
    stream: bool
    extra: dict[str, Any]

    def to_domain(self) -> ChatCompletionRequest:
        domain_messages: list[ChatMessage] = []
        for m in self.messages:
            domain_messages.append(
                ChatMessage(
                    role=m.get("role", ""),
                    content=_upstream_content(m.get("content"), m.get("images")),
                    tool_calls=m.get("tool_calls"),
                    tool_call_id=m.get("tool_call_id"),
                    tool_name=m.get("tool_name"),
                    name=m.get("name"),
                    extra={key: value for key, value in m.items() if key not in _MESSAGE_FIELDS},
                )
            )

        return ChatCompletionRequest(
            model=self.model,
            messages=domain_messages,
            stream=self.stream,
            extra=self.extra,
        )
