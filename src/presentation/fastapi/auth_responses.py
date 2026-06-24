from src.domain.errors import AppError, AuthenticationError
from src.domain.ports.api_key_repository import ApiKeyRepositoryPort
from src.presentation.fastapi.auth_errors import resolve_auth_error
from src.presentation.fastapi.openai_errors import openai_error_response


def openai_auth_error_response(api_key: str, api_key_repo: ApiKeyRepositoryPort):
    err = resolve_auth_error(api_key, api_key_repo)
    if err is None:
        err = AuthenticationError()
    code = err.code if err.code != "AUTH_INVALID_API_KEY" else "invalid_api_key"
    return openai_error_response(
        err.status_code,
        err.message,
        error_type="invalid_request_error",
        code=code,
    )
