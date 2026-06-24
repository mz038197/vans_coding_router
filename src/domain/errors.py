from typing import Any


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


class UpstreamServiceError(AppError):
    def __init__(self, *, status_code: int, backend: str, body: Any):
        super().__init__(
            message="Upstream provider error",
            status_code=status_code,
            code="UPSTREAM_SERVICE_ERROR",
            details={"backend": backend, "body": body},
        )


class ServiceUnavailableError(AppError):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=503,
            code="SERVICE_UNAVAILABLE",
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
