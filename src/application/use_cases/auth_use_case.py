from src.domain.ports.api_key_repository import ApiKeyRepositoryPort


class AuthUseCase:
    def __init__(self, api_key_repo: ApiKeyRepositoryPort):
        self.api_key_repo = api_key_repo

    def verify(self, api_key: str) -> tuple[bool, str | None]:
        if not self.api_key_repo.is_enabled():
            return True, None
        return self.api_key_repo.verify_api_key(api_key)

    def verify_context(self, api_key: str):
        if not self.api_key_repo.is_enabled():
            from src.domain.entities.auth import AuthContext

            return AuthContext(user_id=None, email=None, name=None, role="disabled")
        if hasattr(self.api_key_repo, "verify_api_key_context"):
            return self.api_key_repo.verify_api_key_context(api_key)
        is_valid, teacher_name = self.api_key_repo.verify_api_key(api_key)
        if not is_valid:
            return None
        from src.domain.entities.auth import AuthContext

        return AuthContext(user_id=None, email=None, name=teacher_name, role="legacy")
