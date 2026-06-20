from fastapi import Request
from src.presentation.fastapi.openai_errors import openai_error_response
from starlette.middleware.base import BaseHTTPMiddleware

from src.application.use_cases.auth_use_case import AuthUseCase
from src.domain.errors import AuthenticationError


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_use_case: AuthUseCase):
        super().__init__(app)
        self.auth_use_case = auth_use_case

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/v1/"):
            api_key = None
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                api_key = auth_header[7:]
            else:
                api_key = request.headers.get("X-API-Key")

            auth_context = self.auth_use_case.verify_context(api_key or "")
            is_valid = auth_context is not None
            if not is_valid:
                request.state.invalid_api_key = True
                request.state.api_key = api_key or ""
                if request.url.path not in ("/v1/chat/completions", "/v1/responses"):
                    return openai_error_response(
                        401,
                        AuthenticationError().message,
                        error_type="invalid_request_error",
                        code="invalid_api_key",
                    )
            else:
                request.state.auth_context = auth_context

        response = await call_next(request)
        return response
