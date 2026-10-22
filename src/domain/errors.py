from __future__ import annotations

import json
import math
import re
from typing import Any

_UPSTREAM_AUTH_MESSAGE = (
    "Upstream provider authentication failed. Contact your teacher or administrator."
)
_MAX_UPSTREAM_ERROR_CHARS = 2000
_HTTP_STATUS_PREFIX = re.compile(r"HTTP \d{3}: ")


def extract_upstream_error_text(body: Any) -> str | None:
    """Pull a human-readable message from an upstream error body.

    Providers differ: OpenAI-style ``{"error": {"message": "..."}}``,
    Ollama-style ``{"error": "..."}``, raw JSON strings, or plain text.
    OpenRouter also wraps a provider's own body as ``"HTTP 400: {...}"``,
    and validation failures arrive as a list of located messages.
    """
    if body is None:
        return None

    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")

    if isinstance(body, str):
        text = body.strip()
        if not text:
            return None
        wrapped = _HTTP_STATUS_PREFIX.match(text)
        candidate = text[wrapped.end():] if wrapped else text
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return text[:_MAX_UPSTREAM_ERROR_CHARS]
        if not isinstance(parsed, (dict, list)):
            return text[:_MAX_UPSTREAM_ERROR_CHARS]
        return extract_upstream_error_text(parsed) or text[:_MAX_UPSTREAM_ERROR_CHARS]

    if isinstance(body, list):
        lines = [line for line in (_located_message(item) for item in body) if line]
        return "; ".join(lines)[:_MAX_UPSTREAM_ERROR_CHARS] if lines else None

    if isinstance(body, dict):
        error_obj = body.get("error")
        if isinstance(error_obj, str) and error_obj.strip():
            return extract_upstream_error_text(error_obj)
        if isinstance(error_obj, dict):
            message = error_obj.get("message")
            if isinstance(message, str) and message.strip():
                return extract_upstream_error_text(message)
            nested = error_obj.get("error")
            if isinstance(nested, str) and nested.strip():
                return extract_upstream_error_text(nested)
        detail = body.get("detail")
        if isinstance(detail, (str, dict, list)) and detail:
            return extract_upstream_error_text(detail)
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:_MAX_UPSTREAM_ERROR_CHARS]
        return None

    text = str(body).strip()
    return text[:_MAX_UPSTREAM_ERROR_CHARS] if text else None


def _located_message(item: Any) -> str | None:
    if not isinstance(item, dict):
        return extract_upstream_error_text(item)
    message = item.get("msg") or item.get("message")
    if not isinstance(message, str) or not message.strip():
        return None
    location = item.get("loc") or item.get("path")
    if isinstance(location, list) and location:
        return f"{'.'.join(str(part) for part in location)}: {message.strip()}"
    return message.strip()


class AppError(Exception):
    """跨層共用的應用錯誤基底類型。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        code: str = "APP_ERROR",
        details: Any | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


class AuthenticationError(AppError):
    def __init__(self, message: str = "無效的 API 金鑰", *, code: str = "AUTH_INVALID_API_KEY"):
        super().__init__(
            message=message,
            status_code=401,
            code=code,
        )


class ApiKeyExpiredError(AppError):
    def __init__(self, message: str = "API 金鑰已過期，請至 Portal 重新取得邀請碼"):
        super().__init__(
            message=message,
            status_code=401,
            code="api_key_expired",
        )


class WrongCredentialTypeError(AppError):
    def __init__(
        self,
        message: str = (
            "請使用 Vans Coding Router 的 vcr_sk_ API 金鑰。"
            "在 VS Code 執行 Chat: Manage Language Models → VSRouter → Update API Key"
        ),
    ):
        super().__init__(
            message=message,
            status_code=401,
            code="wrong_credential_type",
        )


class UnresolvedApiKeyPlaceholderError(AppError):
    def __init__(
        self,
        message: str = (
            "VS Code 未解析 API 金鑰（收到 ${apiKey} 占位符）。"
            "請到 Chat: Manage Language Models → VSRouter → Update API Key 重新設定，"
            "然后 Developer: Reload Window"
        ),
    ):
        super().__init__(
            message=message,
            status_code=401,
            code="unresolved_api_key_placeholder",
        )


class UpstreamServiceError(AppError):
    def __init__(self, *, status_code: int, backend: str, body: Any):
        super().__init__(
            message="Upstream provider error",
            status_code=status_code,
            code="UPSTREAM_SERVICE_ERROR",
            details={"backend": backend, "body": body},
        )

    def user_facing_message(self) -> str:
        if self.status_code in (401, 403):
            return _UPSTREAM_AUTH_MESSAGE
        body = (self.details or {}).get("body")
        extracted = extract_upstream_error_text(body)
        return extracted or self.message


class ServiceUnavailableError(AppError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=503,
            code="SERVICE_UNAVAILABLE",
        )


class UpstreamTransportError(ServiceUnavailableError):
    """The upstream could not be reached: a connect, read, or timeout failure."""


class MissingTargetError(AppError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=404,
            code="missing_target",
        )


class NoFreeConcurrencySlotError(Exception):
    """Selectable keys exist, but every one is at its concurrency cap.

    Callers that still have a later Model ID must move on without queueing.
    """


class UpstreamBusyError(AppError):
    def __init__(
        self,
        message: str = (
            "The model provider is busy. Please wait a moment and try again."
        ),
        *,
        public_model: str | None = None,
    ):
        super().__init__(
            message=message,
            status_code=503,
            code="upstream_busy",
        )
        self.public_model = public_model


class QuarantineReleaseCooldownError(AppError):
    def __init__(self, retry_after_sec: float):
        retry_after = max(1, math.ceil(retry_after_sec))
        super().__init__(
            message=f"上游金鑰剛由 Agent 解除隔離，請在 {retry_after} 秒後再試",
            status_code=429,
            code="quarantine_release_cooldown",
            details={"retry_after_sec": retry_after},
        )
        self.retry_after_sec = retry_after


class InvalidJsonBodyError(AppError):
    def __init__(self, message: str = "請求內容必須是 UTF-8 編碼的 JSON 物件"):
        super().__init__(
            message=message,
            status_code=400,
            code="invalid_json_body",
        )


class InvalidModelIdError(AppError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=400,
            code="invalid_model_id",
        )


class ImageGenerationNotSupportedError(AppError):
    def __init__(self, message: str = "此 provider 不支援生圖"):
        super().__init__(
            message=message,
            status_code=400,
            code="image_generation_not_supported",
        )


class ImageGenerationDisabledError(AppError):
    def __init__(self, message: str = "此課堂未開放生圖"):
        super().__init__(
            message=message,
            status_code=403,
            code="image_generation_disabled",
        )


class EmbeddingsDisabledError(AppError):
    def __init__(self, message: str = "此課堂未開放嵌入"):
        super().__init__(
            message=message,
            status_code=403,
            code="embeddings_disabled",
        )


class WebSearchDisabledError(AppError):
    def __init__(self, message: str = "此課堂未開放網路搜尋"):
        super().__init__(
            message=message,
            status_code=403,
            code="web_search_disabled",
        )


class WebSearchRateLimitedError(AppError):
    def __init__(self, message: str = "搜尋太頻繁，請稍後再試"):
        super().__init__(
            message=message,
            status_code=429,
            code="web_search_rate_limited",
        )


class WebSearchUnavailableError(AppError):
    def __init__(self, message: str = "網路搜尋目前無法使用"):
        super().__init__(
            message=message,
            status_code=503,
            code="web_search_unavailable",
        )


class TtsNotSupportedError(AppError):
    def __init__(self, message: str = "此 provider 不支援 /v1/audio/speech"):
        super().__init__(
            message=message,
            status_code=400,
            code="tts_not_supported",
        )


class TtsDisabledError(AppError):
    def __init__(self, message: str = "此課堂未開放語音"):
        super().__init__(
            message=message,
            status_code=403,
            code="tts_disabled",
        )


class ModelNotAllowedError(AppError):
    def __init__(self, message: str = "此課堂未開放此模型"):
        super().__init__(
            message=message,
            status_code=403,
            code="model_not_allowed",
        )


class SpeechTranscriptionNotSupportedError(AppError):
    def __init__(self, message: str = "此 provider 不支援 /v1/audio/transcriptions"):
        super().__init__(
            message=message,
            status_code=400,
            code="speech_transcription_not_supported",
        )


class SpeechTranscriptionDisabledError(AppError):
    def __init__(self, message: str = "此課堂未開放語音轉寫"):
        super().__init__(
            message=message,
            status_code=403,
            code="speech_transcription_disabled",
        )


class DecisionDisabledError(AppError):
    def __init__(self, message: str = "此課堂未開放決策"):
        super().__init__(
            message=message,
            status_code=403,
            code="decision_disabled",
        )


class StatefulResponsesNotSupportedError(AppError):
    def __init__(
        self,
        message: str = "Stateful responses are not supported. Omit previous_response_id.",
    ):
        super().__init__(
            message=message,
            status_code=400,
            code="previous_response_not_found",
        )


class AdminBusinessError(AppError):
    """Admin 業務錯誤（REST 風格）。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "ADMIN_BUSINESS_ERROR",
        status_code: int = 400,
        details: Any | None = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code,
            code=code,
            details=details,
        )
