from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router


def _sqlite_api_client(tmp_path) -> tuple[TestClient, SqliteRouterRepository, FakeLLMGateway]:
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    gateway = FakeLLMGateway()
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=gateway, api_key_repo=repo, logger=FakeRequestLogger())
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    return TestClient(app), repo, gateway


def _student_chat_setup(repo: SqliteRouterRepository):
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    return klass, session, redeem["api_key"]


def test_session_allowlist_rejects_disallowed_chat_model(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    klass, session, student_key = _student_chat_setup(repo)
    repo.update_class_session(
        klass["id"],
        session["id"],
        model_allowlist=["ollama_cloud@minimax-m3:cloud"],
    )
    headers = {"Authorization": f"Bearer {student_key}"}
    body = {"model": "openrouter@minimax/minimax-m3", "messages": [{"role": "user", "content": "hi"}]}

    blocked = client.post("/v1/chat/completions", headers=headers, json=body)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "model_not_allowed"
    assert gateway.last_nonstream_req is None

    allowed = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "ollama_cloud@minimax-m3:cloud", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert allowed.status_code == 200


def test_new_session_chat_rejects_model_id_not_in_template_copy(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    _klass, _session, student_key = _student_chat_setup(repo)
    headers = {"Authorization": f"Bearer {student_key}"}

    blocked = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "anything-goes", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "model_not_allowed"
    assert gateway.last_nonstream_req is None

    allowed = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "ollama_cloud@minimax-m3:cloud", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert allowed.status_code == 200


def test_missing_session_document_rejects_all_chat_models_without_writing(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    klass, session, student_key = _student_chat_setup(repo)
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                "UPDATE class_sessions SET session_chat_language_models_json = NULL WHERE id = ?"
            ),
            (session["id"],),
        )
    blocked = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={"model": "ollama_cloud@minimax-m3:cloud", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "model_not_allowed"
    assert gateway.last_nonstream_req is None
    with repo._connect() as conn:
        stored = conn.execute(
            repo._sql("SELECT session_chat_language_models_json FROM class_sessions WHERE id = ?"),
            (session["id"],),
        ).fetchone()
        assert stored["session_chat_language_models_json"] is None


def test_empty_allowlist_rejects_all_chat_models(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    klass, session, student_key = _student_chat_setup(repo)
    repo.update_class_session(klass["id"], session["id"], model_allowlist=[])
    blocked = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={"model": "ollama_cloud@minimax-m3:cloud", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "model_not_allowed"
    assert gateway.last_nonstream_req is None


def test_allowlist_rejects_disallowed_responses_model(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    klass, session, student_key = _student_chat_setup(repo)
    repo.update_class_session(klass["id"], session["id"], model_allowlist=["ollama_cloud@minimax-m3:cloud"])
    blocked = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {student_key}"},
        json={"model": "openrouter@minimax/minimax-m3", "input": "hi"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "model_not_allowed"
    assert gateway.last_responses_body is None
