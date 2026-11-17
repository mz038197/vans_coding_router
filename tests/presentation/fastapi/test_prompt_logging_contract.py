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

CHAT_BODY = {
    "model": "ollama_cloud@minimax-m3:cloud",
    "messages": [{"role": "user", "content": "hello"}],
}


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


def _student_in_session(repo: SqliteRouterRepository) -> tuple[dict, dict, dict, dict, dict[str, str]]:
    """A teacher's class with one sitting open to any model, and a student who joined it."""
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    with repo._connect() as conn:
        conn.execute(
            repo._sql("UPDATE class_sessions SET classroom_model_choice = NULL WHERE id = ?"),
            (session["id"],),
        )
    student = repo.upsert_google_user("student@school.edu", "Student")
    student_key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    return teacher, klass, session, student, {"Authorization": f"Bearer {student_key}"}


def test_session_prompt_logging_skips_db_when_disabled(tmp_path):
    client, repo, _gateway = _sqlite_api_client(tmp_path)
    teacher, klass, session, student, headers = _student_in_session(repo)

    assert repo.is_prompt_logging_enabled(session["id"]) is True

    enabled = client.post("/v1/chat/completions", headers=headers, json=CHAT_BODY)
    assert enabled.status_code == 200
    assert _prompt_log_count(repo, teacher["id"], klass["id"], session["id"]) == 1
    logs = repo.list_prompt_logs(teacher["id"], klass["id"], session_id=session["id"], limit=1)
    assert logs[0]["total_tokens"] == 33
    assert "hello" in logs[0]["message_preview"]

    repo.update_class_session(klass["id"], session["id"], prompt_logging_enabled=False)
    assert repo.is_prompt_logging_enabled(session["id"]) is False

    disabled = client.post("/v1/chat/completions", headers=headers, json=CHAT_BODY)
    assert disabled.status_code == 200
    assert _prompt_log_count(repo, teacher["id"], klass["id"], session["id"]) == 1

    usage = repo.class_usage(teacher["id"], klass["id"])
    student_usage = next(row for row in usage if row["user_id"] == student["id"])
    # Token Usage is recorded whether or not prompt logging is on.
    assert student_usage["total_tokens"] == 66

    repo.update_class_session(klass["id"], session["id"], prompt_logging_enabled=True)

    reenabled = client.post("/v1/chat/completions", headers=headers, json=CHAT_BODY)
    assert reenabled.status_code == 200
    assert _prompt_log_count(repo, teacher["id"], klass["id"], session["id"]) == 2


def test_prompt_log_records_the_caller_ip_fly_reports(tmp_path):
    client, repo, _gateway = _sqlite_api_client(tmp_path)
    teacher, klass, session, _student, headers = _student_in_session(repo)

    behind_fly = client.post(
        "/v1/chat/completions",
        headers={**headers, "Fly-Client-IP": "203.0.113.7"},
        json=CHAT_BODY,
    )
    direct = client.post("/v1/chat/completions", headers=headers, json=CHAT_BODY)

    assert behind_fly.status_code == 200
    assert direct.status_code == 200
    logs = repo.list_prompt_logs(teacher["id"], klass["id"], session_id=session["id"], limit=10)
    assert sorted(log["client_ip"] for log in logs) == ["203.0.113.7", "testclient"]


def test_stream_still_completes_when_the_prompt_log_cannot_be_written(tmp_path, monkeypatch, caplog):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    teacher, klass, _session, student, headers = _student_in_session(repo)

    def broken_log_prompt(**_kwargs):
        raise RuntimeError("prompt_logs is unavailable")

    monkeypatch.setattr(repo, "log_prompt", broken_log_prompt)

    response = client.post("/v1/chat/completions", headers=headers, json={**CHAT_BODY, "stream": True})

    assert response.status_code == 200
    assert response.content == b"".join(gateway.stream_chunks)
    assert any(
        record.levelname == "ERROR" and "prompt log" in record.getMessage().lower() for record in caplog.records
    )
    # Token Usage is written before the Prompt Log, so the failure loses only the log.
    student_usage = next(row for row in repo.class_usage(teacher["id"], klass["id"]) if row["user_id"] == student["id"])
    assert student_usage["request_count"] == 1
