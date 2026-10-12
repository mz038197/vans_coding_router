from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatMessageSchema(BaseModel):
    """支援 OpenAI 相容格式的聊天訊息"""
    role: str
    # 區塊陣列不解析成模型：上游要拿到客戶端送的原樣區塊。
    content: str | list[Any] | None = Field(
        default=None,
        description="訊息內容；assistant 可僅有 tool_calls；tool 角色可為空字串",
    )
    images: list[str] | None = Field(default=None, description="影像資料陣列（base64 編碼或 URL）")
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    tool_name: str | None = Field(default=None, description="相容舊客戶端的 tool 結果函數名")

    model_config = {"extra": "allow"}

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

        # 舊客戶端只貼圖不打字：圖片就是 user 訊息的內容。
        image_only_user = role == "user" and any(self.images or [])
        if role in ("user", "system") and not image_only_user:
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
    messages: list[ChatMessageSchema] = Field(min_length=1)
    stream: bool = False

    # 其他欄位不驗證，原樣轉發給上游。
    model_config = {"extra": "allow"}


class ImageGenerationRequestSchema(BaseModel):
    model: str
    prompt: str
    stream: bool = False
    n: int | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    quality: str | None = None
    output_format: str | None = None
    background: str | None = None
    output_compression: int | None = None
    seed: int | None = None
    input_references: list[dict[str, Any]] | None = None
    provider: dict[str, Any] | None = None

    model_config = {"extra": "allow"}

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt 不可為空")
        return v


class WebSearchRequestSchema(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)

    @field_validator("queries")
    @classmethod
    def validate_queries(cls, v: list[str]) -> list[str]:
        for query in v:
            if not query.strip() or len(query) > 1000:
                raise ValueError("每個查詢必須是 1 到 1000 個字元")
        return v


class AudioSpeechRequestSchema(BaseModel):
    model: str
    input: str
    voice: str
    response_format: str | None = None
    speed: float | None = None
    instructions: str | None = None

    model_config = {"extra": "allow"}

    @field_validator("input")
    @classmethod
    def validate_input(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("input 不可為空")
        return v
