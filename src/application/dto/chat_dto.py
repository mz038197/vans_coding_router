from dataclasses import dataclass
from typing import Any

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage


def _normalize_image_value(value: Any) -> str | None:
    """將 image 值正規化為 Ollama 可接受的字串格式。"""
    if not isinstance(value, str):
        return None

    # Ollama images 欄位通常要純 base64；若收到 data URL 則去掉前綴。
    if value.startswith("data:") and ";base64," in value:
        return value.split(";base64,", 1)[1]
    return value


def _extract_content_and_images(content: Any, explicit_images: list[str] | None = None) -> tuple[str, list[str] | None]:
    """從 content 中提取文本和影像。
    
    支援兩種格式：
    1. 簡單格式：content 是字符串
    2. OpenAI 格式：content 是包含文本和影像物件的陣列
    """
    if content is None:
        return "", explicit_images if explicit_images else None
    images: list[str] = []
    for item in explicit_images or []:
        normalized = _normalize_image_value(item)
        if normalized:
            images.append(normalized)
    text_parts: list[str] = []
    
    if isinstance(content, str):
        return content, images if images else None
    
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and "text" in item:
                    text_parts.append(item["text"])
                elif item.get("type") == "image_url" and "image_url" in item:
                    image_url = item["image_url"]
                    if isinstance(image_url, dict) and "url" in image_url:
                        normalized = _normalize_image_value(image_url["url"])
                        if normalized:
                            images.append(normalized)
                    elif isinstance(image_url, str):
                        normalized = _normalize_image_value(image_url)
                        if normalized:
                            images.append(normalized)
        
        return " ".join(text_parts), images if images else None
    
    return "", images if images else None


@dataclass
class ChatCompletionInputDto:
    model: str
    messages: list[dict[str, Any]]
    stream: bool
    temperature: float | None
    max_tokens: int | None
    user: str | None
    stop: object | None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None

    def to_domain(self) -> ChatCompletionRequest:
        domain_messages: list[ChatMessage] = []
        for m in self.messages:
            content, images = _extract_content_and_images(m.get("content"), m.get("images"))
            domain_messages.append(
                ChatMessage(
                    role=m.get("role", ""),
                    content=content,
                    images=images,
                    tool_calls=m.get("tool_calls"),
                    tool_call_id=m.get("tool_call_id"),
                    tool_name=m.get("tool_name"),
                    name=m.get("name"),
                )
            )

        return ChatCompletionRequest(
            model=self.model,
            messages=domain_messages,
            stream=self.stream,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            user=self.user,
            stop=self.stop,
            tools=self.tools,
            tool_choice=self.tool_choice,
        )
