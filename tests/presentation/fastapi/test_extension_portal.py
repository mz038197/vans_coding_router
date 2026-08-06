"""Extension Sign-in Handoff + redeem + model template APIs."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.auth.google_oauth import GoogleOAuthService, GoogleUserClaims
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template
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
        ),
    )


def _client(tmp_path, **settings_kwargs):
    settings = _settings(tmp_path, **settings_kwargs)
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    app.include_router(create_portal_router(PortalUseCase(repo, settings), settings))
    return TestClient(app), repo, settings


def test_chat_language_models_template_is_public(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/extension/chat-language-models")
    assert response.status_code == 200
    assert response.json() == load_vans_template()


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


def test_extension_course_catalog_get_and_after_session_end(tmp_path):
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
        cookies={"session_user_id": str(teacher["id"])},
        json={"course_catalog_yaml": yaml_body},
    )
    assert patch.status_code == 200
    assert "demo" in patch.json()["course_catalog_yaml"]

    bad = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies={"session_user_id": str(teacher["id"])},
        json={"course_catalog_yaml": "actions:\n  - id: x\n"},
    )
    assert bad.status_code == 400

    client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies={"session_user_id": str(teacher["id"])},
        json={"status": "ended"},
    )
    after_end = client.get(
        "/extension/course-catalog",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert after_end.status_code == 200
    assert "demo" in after_end.json()["course_catalog_yaml"]


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
