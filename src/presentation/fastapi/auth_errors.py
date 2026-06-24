from src.domain.errors import ApiKeyExpiredError, AppError, AuthenticationError, WrongCredentialTypeError
from src.domain.ports.api_key_repository import ApiKeyRepositoryPort
from src.infrastructure.auth.client_api_key import classify_client_api_key, normalize_api_key


def resolve_auth_error(api_key: str, api_key_repo: ApiKeyRepositoryPort) -> AppError | None:
    api_key = normalize_api_key(api_key)
    format_reason = classify_client_api_key(api_key)
    if format_reason == "copilot_token":
        return WrongCredentialTypeError()
    if format_reason == "unresolved_placeholder":
        return UnresolvedApiKeyPlaceholderError()
    if format_reason in {"missing"}:
        return AuthenticationError()

    if not api_key_repo.is_enabled():
        return None

    if hasattr(api_key_repo, "verify_api_key_with_reason"):
        _, failure = api_key_repo.verify_api_key_with_reason(api_key)
        if failure == "expired":
            return ApiKeyExpiredError()
        if failure in {"invalid", "disabled", "missing"}:
            return AuthenticationError()
        return None

    is_valid, _ = api_key_repo.verify_api_key(api_key)
    if not is_valid:
        return AuthenticationError()
    return None
