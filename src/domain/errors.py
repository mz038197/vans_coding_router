from __future__ import annotations

import json
from typing import Any

_UPSTREAM_AUTH_MESSAGE = (
    "Upstream provider authentication failed. Contact your teacher or administrator."
)
_MAX_UPSTREAM_ERROR_CHARS = 2000


def extract_upstream_error_text(body: Any) -> str | None:
    """Pull a human-readable message from an upstream error body.

    Providers differ: OpenAI-style ``{"error": {"message": "..."}}``,
    Ollama-style ``{"error": "..."}``, raw JSON strings, or plain text.
    """
    if body is None:
        return None

    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")

    if isinstance(body, str):
        text = body.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text[:_MAX_UPSTREAM_ERROR_CHARS]
        return extract_upstream_error_text(parsed)

    if isinstance(body, dict):
        error_obj = body.get("error")
        if isinstance(error_obj, str) and error_obj.strip():
            return error_obj.strip()[:_MAX_UPSTREAM_ERROR_CHARS]
        if isinstance(error_obj, dict):
            message = error_obj.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:_MAX_UPSTREAM_ERROR_CHARS]
            nested = error_obj.get("error")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()[:_MAX_UPSTREAM_ERROR_CHARS]
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:_MAX_UPSTREAM_ERROR_CHARS]
        return None

    text = str(body).strip()
    return text[:_MAX_UPSTREAM_ERROR_CHARS] if text else None


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


class UpstreamBusyError(AppError):
    def __init__(
        self,
        message: str = (
            "The model provider is busy. Please wait a moment and try again."
        ),
    ):
        super().__init__(
            message=message,
            status_code=503,
            code="upstream_busy",
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
