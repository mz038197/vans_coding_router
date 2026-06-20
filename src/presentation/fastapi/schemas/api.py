from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ContentPart(BaseModel):
    """表示 content 陣列中的單個部分"""
    type: str
    text: str | None = None
    image_url: dict[str, str] | None = None


class ChatMessageSchema(BaseModel):
    """支援 OpenAI 相容格式的聊天訊息"""
    role: str
    content: str | list[ContentPart | dict[str, Any]] | None = Field(
        default=None,
        description="訊息內容；assistant 可僅有 tool_calls；tool 角色可為空字串",
    )
    images: list[str] | None = Field(default=None, description="影像資料陣列（base64 編碼或 URL）")
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    tool_name: str | None = Field(default=None, description="相容舊客戶端的 tool 結果函數名")

    @field_validator("content", mode="before")
    @classmethod
    def validate_content_shape(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return v
        raise ValueError("訊息內容必須是字符串、陣列或 null")

    @model_validator(mode="after")
    def validate_content_by_role(self) -> "ChatMessageSchema":
        role = self.role
        c = self.content
        tc = self.tool_calls

        if role in ("user", "system"):
            if c is None:
                raise ValueError("訊息內容不能為空")
            if isinstance(c, str) and not c.strip():
                raise ValueError("訊息內容不能為空")
            if isinstance(c, list) and not c:
                raise ValueError("訊息內容不能為空陣列")
        elif role == "assistant":
            has_tc = bool(tc)
            if c is None and not has_tc:
                raise ValueError("assistant 訊息必須有 content 或 tool_calls")
            if isinstance(c, str) and not c.strip() and not has_tc:
                raise ValueError("assistant 訊息必須有 content 或 tool_calls")
            if isinstance(c, list) and not c and not has_tc:
                raise ValueError("assistant 訊息必須有 content 或 tool_calls")
        elif role == "tool":
            if self.tool_call_id is None:
                raise ValueError("tool 訊息必須有 tool_call_id")
            if c is None:
                self.content = ""
        return self


class ChatCompletionsRequestSchema(BaseModel):
    model: str
    messages: list[ChatMessageSchema]
    stream: bool = False
    temperature: float | None = 0.7
    max_tokens: int | None = 200000
    user: str | None = None
    stop: Any | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
