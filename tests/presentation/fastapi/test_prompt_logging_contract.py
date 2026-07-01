from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from fakes import FakeLLMGateway, FakeRequestLogger


def _sqlite_api_client(tmp_path) -> tuple[TestClient, SqliteRouterRepository, FakeLLMGateway]:
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    gateway = FakeLLMGateway()
    gateway.nonstream_response = {
        **gateway.nonstream_response,
        "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
    }
    logger = FakeRequestLogger()
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=gateway, api_key_repo=repo, logger=logger)
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    return TestClient(app), repo, gateway


def _prompt_log_count(repo: SqliteRouterRepository, teacher_id: int, class_id: int, session_id: int) -> int:
    return len(
        repo.list_prompt_logs(
            teacher_id,
            class_id,
            session_id=session_id,
            limit=100,
        )
    )


def test_session_prompt_logging_skips_db_when_disabled(tmp_path):
    client, repo, _gateway = _sqlite_api_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    student_key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    headers = {"Authorization": f"Bearer {student_key}"}
    body = {"model": "fake-model", "messages": [{"role": "user", "content": "hello"}]}

    assert repo.is_prompt_logging_enabled(session["id"]) is True

    enabled = client.post("/v1/chat/completions", headers=headers, json=body)
    assert enabled.status_code == 200
    assert _prompt_log_count(repo, teacher["id"], klass["id"], session["id"]) == 1
    logs = repo.list_prompt_logs(teacher["id"], klass["id"], session_id=session["id"], limit=1)
    assert logs[0]["total_tokens"] == 33
    assert "hello" in logs[0]["message_preview"]

    repo.update_class_session(klass["id"], session["id"], prompt_logging_enabled=False)
    assert repo.is_prompt_logging_enabled(session["id"]) is False

    disabled = client.post("/v1/chat/completions", headers=headers, json=body)
    assert disabled.status_code == 200
    assert _prompt_log_count(repo, teacher["id"], klass["id"], session["id"]) == 1

    usage = repo.class_usage(teacher["id"], klass["id"])
    student_usage = next(row for row in usage if row["user_id"] == student["id"])
    assert student_usage["total_tokens"] == 33

    repo.update_class_session(klass["id"], session["id"], prompt_logging_enabled=True)

    reenabled = client.post("/v1/chat/completions", headers=headers, json=body)
    assert reenabled.status_code == 200
    assert _prompt_log_count(repo, teacher["id"], klass["id"], session["id"]) == 2
