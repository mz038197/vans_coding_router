from src.application.use_cases.auth_use_case import AuthUseCase


def test_verify_returns_true_when_key_system_disabled():
    class DisabledRepo:
        def is_enabled(self) -> bool:
            return False

        def verify_api_key(self, api_key: str):
            raise AssertionError("disabled mode should not verify")

    use_case = AuthUseCase(api_key_repo=DisabledRepo())
    assert use_case.verify("") == (True, None)


def test_verify_context_returns_default_context_when_key_system_disabled():
    class DisabledRepo:
        def is_enabled(self) -> bool:
            return False

        def verify_api_key(self, api_key: str):
            raise AssertionError("disabled mode should not verify")

    use_case = AuthUseCase(api_key_repo=DisabledRepo())
    context = use_case.verify_context("")

    assert context is not None
    assert context.role == "disabled"
    assert context.teacher_name is None


def test_verify_returns_repo_result_when_enabled(fake_repo):
    use_case = AuthUseCase(api_key_repo=fake_repo)
    assert use_case.verify("valid-key") == (True, "TeacherA")
    assert use_case.verify("bad-key") == (False, None)
