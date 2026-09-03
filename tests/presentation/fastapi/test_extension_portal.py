"""Extension Sign-in Handoff + redeem + model template APIs."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.auth.google_oauth import GoogleOAuthService, GoogleUserClaims
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.domain.session_model_allowlist import template_model_ids
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from src.presentation.fastapi.routers.portal_router import create_portal_router


def _settings(tmp_path, *, google_client_id: str = "", google_client_secret: str = "") -> RouterSettings:
    return RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-session-secret",
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            dev_auth_enabled=True,
        ),
    )


def _client(tmp_path, **settings_kwargs):
    settings = _settings(tmp_path, **settings_kwargs)
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    register_error_handlers(app)
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=FakeLLMGateway(), api_key_repo=repo, logger=FakeRequestLogger())
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    app.include_router(create_portal_router(PortalUseCase(repo, settings), settings))
    return TestClient(
        app,
        base_url="http://127.0.0.1",
        headers={"Origin": settings.public_url},
    ), repo, settings


def _redeem_student_key(client, invite_code: str) -> str:
    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={"handoff_token": login.json()["handoff_token"], "invite_code": invite_code},
    )
    return redeem.json()["api_key"]


def _end_session(client, repo, teacher_id: int, class_id: int, session_id: int) -> None:
    ended = client.patch(
        f"/teacher/classes/{class_id}/sessions/{session_id}",
        cookies=_portal_cookie(repo, teacher_id),
        json={"status": "ended"},
    )
    assert ended.status_code == 200


def _portal_cookie(repo, user_id: int) -> dict[str, str]:
    token, _ = repo.create_portal_session(user_id, "Test browser")
    return {"vcr_portal_session": token}


def test_chat_language_models_template_is_public(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/extension/chat-language-models")
    assert response.status_code == 200
    assert response.json() == load_vans_template()


def test_creating_class_session_keyed_get_returns_template_copy(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    created = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"name": "Week 1"},
    )
    assert created.status_code == 200
    assert created.json()["session_chat_language_models"] == load_vans_template()
    api_key = _redeem_student_key(client, created.json()["invite_code"])

    keyed = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert keyed.status_code == 200
    assert keyed.json() == load_vans_template()


def test_missing_session_document_is_copied_on_ship_not_student_get(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    api_key = _redeem_student_key(client, session["invite_code"])
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                "UPDATE class_sessions SET session_chat_language_models_json = NULL WHERE id = ?"
            ),
            (session["id"],),
        )

    before_ship = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert before_ship.status_code == 200
    assert before_ship.json() == []
    with repo._connect() as conn:
        stored = conn.execute(
            repo._sql("SELECT session_chat_language_models_json FROM class_sessions WHERE id = ?"),
            (session["id"],),
        ).fetchone()
        assert stored["session_chat_language_models_json"] is None

    shipped, _, _ = _client(tmp_path)
    after_ship = shipped.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert after_ship.status_code == 200
    assert after_ship.json() == load_vans_template()


def test_keyed_chat_language_models_returns_session_document_not_live_template(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    document = [
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "models": [{"id": "ollama_cloud@minimax-m3:cloud", "name": "sitting-only"}],
        }
    ]
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=document,
    )
    api_key = _redeem_student_key(client, session["invite_code"])

    keyed = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert keyed.status_code == 200
    assert keyed.json() == document

    public = client.get("/extension/chat-language-models")
    assert public.status_code == 200
    assert public.json() == load_vans_template()
    assert public.json() != document


def test_chat_language_models_bearer_filters_session_allowlist(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    allowed = "ollama_cloud@minimax-m3:cloud"
    other = "openrouter@minimax/minimax-m3"
    patch = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"model_allowlist": [allowed]},
    )
    assert patch.status_code == 200
    assert patch.json()["model_allowlist"] == [allowed]

    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={
            "handoff_token": login.json()["handoff_token"],
            "invite_code": session["invite_code"],
        },
    )
    api_key = redeem.json()["api_key"]
    filtered = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert filtered.status_code == 200
    ids = [model["id"] for model in filtered.json()[0]["models"]]
    assert ids == [allowed]
    assert other not in ids

    empty = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"model_allowlist": []},
    )
    assert empty.status_code == 200
    assert empty.json()["model_allowlist"] == []
    emptied = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert emptied.json()[0]["name"] == "VCRouter"
    assert emptied.json()[0]["models"] == []

    restored_session = repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=load_vans_template(),
    )
    assert restored_session is not None
    assert restored_session["model_allowlist"] == template_model_ids(load_vans_template())
    restored = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert restored.json() == load_vans_template()


def test_chat_language_models_invalid_bearer_is_forbidden(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": "Bearer vcr_sk_not-a-real-key"},
    )
    assert response.status_code == 403


def test_chat_language_models_personal_key_returns_full_template(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    personal = repo.issue_long_lived_key(teacher["id"])
    response = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {personal}"},
    )
    assert response.status_code == 200
    assert response.json() == load_vans_template()


def test_session_model_allowlist_rejects_ids_outside_template(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    response = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"model_allowlist": ["unknown@not-in-template"]},
    )
    assert response.status_code == 400


def test_dev_google_login_returns_handoff_for_extension_client(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "handoff_token" in body
    assert body["user"]["email"] == "student@gmail.com"


def test_extension_redeem_with_handoff(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")

    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    token = login.json()["handoff_token"]

    redeem = client.post(
        "/extension/sessions/redeem",
        json={"handoff_token": token, "invite_code": session["invite_code"]},
    )
    assert redeem.status_code == 200
    data = redeem.json()
    assert data["api_key"].startswith("vcr_sk_")
    assert data["session"]["invite_code"] == session["invite_code"]

    reuse = client.post(
        "/extension/sessions/redeem",
        json={"handoff_token": token, "invite_code": session["invite_code"]},
    )
    assert reuse.status_code == 400


def test_extension_course_catalog_get_and_fails_after_session_end(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    assert "actions:" in (session.get("course_catalog_yaml") or "")

    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={
            "handoff_token": login.json()["handoff_token"],
            "invite_code": session["invite_code"],
        },
    )
    api_key = redeem.json()["api_key"]

    catalog = client.get(
        "/extension/course-catalog",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert catalog.status_code == 200
    assert "actions:" in catalog.json()["course_catalog_yaml"]

    yaml_body = """
actions:
  - id: demo
    title: Demo
    kind: package
    command: uv add demo
"""
    patch = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"course_catalog_yaml": yaml_body},
    )
    assert patch.status_code == 200
    assert "demo" in patch.json()["course_catalog_yaml"]

    bad = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"course_catalog_yaml": "actions:\n  - id: x\n"},
    )
    assert bad.status_code == 400

    client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"status": "ended"},
    )
    after_end = client.get(
        "/extension/course-catalog",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert after_end.status_code == 401
    assert after_end.json()["detail"] == "API 金鑰已過期，請至 Portal 重新取得邀請碼"


def test_keyed_chat_language_models_fails_after_session_end(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    api_key = _redeem_student_key(client, session["invite_code"])

    live = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert live.status_code == 200
    assert live.json() == load_vans_template()

    _end_session(client, repo, teacher["id"], klass["id"], session["id"])
    after_end = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert after_end.status_code == 401
    assert after_end.json()["detail"] == "API 金鑰已過期，請至 Portal 重新取得邀請碼"

    public = client.get("/extension/chat-language-models")
    assert public.status_code == 200
    assert public.json() == load_vans_template()


def test_v1_chat_still_fails_after_session_end(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    api_key = _redeem_student_key(client, session["invite_code"])
    _end_session(client, repo, teacher["id"], klass["id"], session["id"])

    chat = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": "ollama_cloud@minimax-m3:cloud", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert chat.status_code == 401
    assert chat.json()["error"]["code"] == "api_key_expired"


def test_disabled_key_fails_extension_gets(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    api_key = _redeem_student_key(client, session["invite_code"])
    with repo._connect() as conn:
        conn.execute(
            repo._sql("UPDATE api_keys SET enabled = ? WHERE key_hash = ?"),
            (repo._disabled_enabled_value(), repo._hash_key(api_key)),
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    catalog = client.get("/extension/course-catalog", headers=headers)
    models = client.get("/extension/chat-language-models", headers=headers)
    assert catalog.status_code == 403
    assert models.status_code == 403


def test_suspended_user_fails_extension_gets(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    api_key = _redeem_student_key(client, session["invite_code"])
    student = repo.get_user_by_email("student@gmail.com")
    assert student is not None
    disable = client.patch(
        f"/teacher/classes/{klass['id']}/members/{student['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"status": "inactive"},
    )
    assert disable.status_code == 200

    headers = {"Authorization": f"Bearer {api_key}"}
    catalog = client.get("/extension/course-catalog", headers=headers)
    models = client.get("/extension/chat-language-models", headers=headers)
    assert catalog.status_code == 403
    assert models.status_code == 403


def test_teacher_patch_dumps_multiline_snippet_body_as_block_scalar(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    snippet_yaml = """
actions: []
snippets:
  - id: stub
    title: Stub
    body: "def main():\\n    pass\\n"
"""
    response = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"course_catalog_yaml": snippet_yaml},
    )
    assert response.status_code == 200
    dumped = response.json()["course_catalog_yaml"]
    assert "body: |" in dumped
    assert '"def main():' not in dumped


def test_google_login_start_sets_extension_client_cookie(tmp_path):
    client, _, _ = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    response = client.get("/auth/google/login?client=extension", follow_redirects=False)
    assert response.status_code == 302
    assert response.cookies.get("oauth_client") == "extension"


def test_google_callback_extension_client_redirects_to_handoff_page(tmp_path):
    client, _, settings = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    oauth = GoogleOAuthService(
        client_id=settings.auth.google_client_id,
        client_secret=settings.auth.google_client_secret,
        redirect_uri="http://testserver/auth/google/callback",
        session_secret=settings.auth.session_secret,
    )
    state = oauth.create_state()
    claims = GoogleUserClaims(email="student@gmail.com", name="Student", google_sub="sub-1")

    with patch(
        "src.presentation.fastapi.routers.portal_router.GoogleOAuthService.exchange_code",
        new=AsyncMock(return_value=claims),
    ):
        response = client.get(
            f"/auth/google/callback?code=fake-code&state={state}",
            cookies={"oauth_state": state, "oauth_client": "extension"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("/auth/extension/complete?token=")
