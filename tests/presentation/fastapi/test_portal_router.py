import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.auth.google_oauth import GoogleOAuthService, GoogleUserClaims
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
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


def test_google_oauth_state_roundtrip():
    service = GoogleOAuthService(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://testserver/auth/google/callback",
        session_secret="secret",
    )
    state = service.create_state()
    assert service.verify_state(state)


def test_google_oauth_state_rejects_tampered_signature():
    service = GoogleOAuthService(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://testserver/auth/google/callback",
        session_secret="secret",
    )
    state = service.create_state()
    assert not service.verify_state(state + "x")


def test_google_oauth_state_rejects_expired_state():
    service = GoogleOAuthService(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://testserver/auth/google/callback",
        session_secret="secret",
    )
    with patch("src.infrastructure.auth.google_oauth.time.time", return_value=time.time() - 700):
        state = service.create_state()
    assert not service.verify_state(state)


def test_auth_config_reports_oauth_disabled(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/auth/config")
    assert response.status_code == 200
    assert response.json() == {"oauth_enabled": False, "redirect_uri": None}


def test_auth_config_reports_oauth_enabled(tmp_path):
    client, _, _ = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    response = client.get("/auth/config")
    assert response.status_code == 200
    assert response.json() == {
        "oauth_enabled": True,
        "redirect_uri": "http://testserver/auth/google/callback",
    }


def test_dev_google_login_works_when_oauth_disabled(tmp_path):
    client, repo, _ = _client(tmp_path)
    response = client.post("/auth/google", json={"email": "student@gmail.com", "name": "Student"})
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["email"] == "student@gmail.com"
    assert response.cookies.get("session_user_id") == str(user["id"])
    assert repo.get_user_by_email("student@gmail.com") is not None


def test_dev_google_login_blocked_when_oauth_enabled(tmp_path):
    client, _, _ = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    response = client.post("/auth/google", json={"email": "student@gmail.com", "name": "Student"})
    assert response.status_code == 403


def test_google_login_start_redirects_when_configured(tmp_path):
    client, _, _ = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    response = client.get("/auth/google/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert response.cookies.get("oauth_state")


def test_google_login_start_returns_503_when_not_configured(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/auth/google/login")
    assert response.status_code == 503


def test_google_callback_sets_session_cookie(tmp_path):
    client, repo, settings = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    oauth = GoogleOAuthService(
        client_id=settings.auth.google_client_id,
        client_secret=settings.auth.google_client_secret,
        redirect_uri="http://testserver/auth/google/callback",
        session_secret=settings.auth.session_secret,
    )
    state = oauth.create_state()
    claims = GoogleUserClaims(email="student@gmail.com", name="Student", google_sub="google-sub-1")

    with patch(
        "src.presentation.fastapi.routers.portal_router.GoogleOAuthService.exchange_code",
        new=AsyncMock(return_value=claims),
    ):
        response = client.get(
            f"/auth/google/callback?code=fake-code&state={state}",
            cookies={"oauth_state": state},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/portal"
    assert response.cookies.get("session_user_id") == "1"
    saved = repo.get_user_by_email("student@gmail.com")
    assert saved is not None
    assert saved["google_sub"] == "google-sub-1"


def test_google_callback_rejects_invalid_state(tmp_path):
    client, _, settings = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    oauth = GoogleOAuthService(
        client_id=settings.auth.google_client_id,
        client_secret=settings.auth.google_client_secret,
        redirect_uri="http://testserver/auth/google/callback",
        session_secret=settings.auth.session_secret,
    )
    state = oauth.create_state()
    response = client.get(
        f"/auth/google/callback?code=fake-code&state={state}",
        cookies={"oauth_state": "wrong-state"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "login_error=" in response.headers["location"]


def test_portal_permission_error_returns_403(tmp_path):
    client, repo, _ = _client(tmp_path)
    student = repo.upsert_google_user("student@example.com", "Student")

    response = client.get("/admin/users", cookies={"session_user_id": str(student["id"])})

    assert response.status_code == 403
    assert response.json()["detail"] == "權限不足"


def test_admin_archive_run_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")

    response = client.post("/admin/archive/run", cookies={"session_user_id": str(admin["id"])})

    assert response.status_code == 200
    assert response.json() == {"archived": 0}


def test_admin_update_settings_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")

    response = client.patch(
        "/admin/settings",
        cookies={"session_user_id": str(admin["id"])},
        json={"retention_days": 10, "student_default_ttl_hours": 4, "open_registration": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["prompt_logs"]["retention_days"] == 10
    assert payload["student_default_ttl_hours"] == 4
    assert payload["auth"]["open_registration"] is False


def test_admin_update_class_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)

    response = client.patch(
        f"/admin/classes/{klass['id']}",
        cookies={"session_user_id": str(admin["id"])},
        json={"status": "ended"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ended"
