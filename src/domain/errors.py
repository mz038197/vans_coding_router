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
    def __init__(self, message: str = "無效的 API 金鑰"):
        super().__init__(
            message=message,
            status_code=401,
            code="AUTH_INVALID_API_KEY",
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
