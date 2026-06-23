from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.domain.errors import (
    AdminBusinessError,
    AppError,
    AuthenticationError,
    ImageGenerationDisabledError,
    ImageGenerationNotSupportedError,
    InvalidModelIdError,
    ServiceUnavailableError,
    StatefulResponsesNotSupportedError,
    TtsDisabledError,
    TtsNotSupportedError,
    UpstreamServiceError,
)
from src.presentation.fastapi.openai_errors import (
    is_openai_compatible_path,
    make_openai_error_body,
    openai_error_response,
)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def handle_authentication_error(request: Request, exc: AuthenticationError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="invalid_request_error",
                code="invalid_api_key",
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(UpstreamServiceError)
    async def handle_upstream_error(request: Request, exc: UpstreamServiceError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="server_error",
            )
        details = exc.details or {}
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": {
                    "message": "Upstream provider error",
                    "backend": details.get("backend", ""),
                    "body": details.get("body", ""),
                }
            },
        )

    @app.exception_handler(ServiceUnavailableError)
    async def handle_service_unavailable(request: Request, exc: ServiceUnavailableError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="server_error",
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(InvalidModelIdError)
    async def handle_invalid_model_id_error(request: Request, exc: InvalidModelIdError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="invalid_request_error",
                code=exc.code,
                param="model",
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(ImageGenerationNotSupportedError)
    async def handle_image_generation_not_supported(request: Request, exc: ImageGenerationNotSupportedError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="invalid_request_error",
                code=exc.code,
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(ImageGenerationDisabledError)
    async def handle_image_generation_disabled(request: Request, exc: ImageGenerationDisabledError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="invalid_request_error",
                code=exc.code,
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(TtsNotSupportedError)
    async def handle_tts_not_supported(request: Request, exc: TtsNotSupportedError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="invalid_request_error",
                code=exc.code,
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(TtsDisabledError)
    async def handle_tts_disabled(request: Request, exc: TtsDisabledError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="invalid_request_error",
                code=exc.code,
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(StatefulResponsesNotSupportedError)
    async def handle_stateful_responses_error(request: Request, exc: StatefulResponsesNotSupportedError):
        if is_openai_compatible_path(request.url.path):
            return openai_error_response(
                exc.status_code,
                exc.message,
                error_type="invalid_request_error",
                code=exc.code,
                param="previous_response_id",
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(AdminBusinessError)
    async def handle_admin_business_error(_: Request, exc: AdminBusinessError):
        payload = {
            "detail": {
                "code": exc.code,
                "message": exc.message,
            }
        }
        if exc.details is not None:
            payload["detail"]["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        if is_openai_compatible_path(request.url.path):
            return JSONResponse(
                status_code=exc.status_code,
                content=make_openai_error_body(
                    exc.message,
                    error_type="api_error",
                    code=exc.code,
                ),
            )
        payload = {"detail": exc.message}
        if exc.details is not None:
            payload["error"] = {"code": exc.code, "details": exc.details}
        return JSONResponse(status_code=exc.status_code, content=payload)
