import re
import time
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.auth.google_oauth import GoogleOAuthService, GoogleUserClaims
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.portal_router import create_portal_router


def _settings(
    tmp_path,
    *,
    google_client_id: str = "",
    google_client_secret: str = "",
    dev_auth_enabled: bool = True,
) -> RouterSettings:
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
            dev_auth_enabled=dev_auth_enabled,
        ),
    )


def _client(tmp_path, llm_gateway=None, base_url="http://127.0.0.1", **settings_kwargs):
    settings = _settings(tmp_path, **settings_kwargs)
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    app.include_router(
        create_portal_router(PortalUseCase(repo, settings, llm_gateway=llm_gateway), settings)
    )
    return (
        TestClient(
            app,
            base_url=base_url,
            headers={"Origin": settings.public_url.rstrip("/")},
        ),
        repo,
        settings,
    )


def _portal_cookie(repo, user: dict) -> dict[str, str]:
    token, _ = repo.create_portal_session(user["id"], "Test browser")
    return {"vcr_portal_session": token}


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
    assert response.json() == {
        "oauth_enabled": False,
        "redirect_uri": None,
        "public_url": "http://testserver",
    }


def test_auth_config_reports_oauth_enabled(tmp_path):
    client, _, _ = _client(tmp_path, google_client_id="cid", google_client_secret="csecret")
    response = client.get("/auth/config")
    assert response.status_code == 200
    assert response.json() == {
        "oauth_enabled": True,
        "redirect_uri": "http://testserver/auth/google/callback",
        "public_url": "http://testserver",
    }


def test_portal_brand_logo_served(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/portal/static/brand-logo.png")
    assert response.status_code == 200
    assert "image/png" in response.headers.get("content-type", "")
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_portal_page_uses_brand_logo_in_both_navs(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert html.count('src="/portal/static/brand-logo.png"') == 2
    assert 'class="nav-logo"' in html
    assert "fa-route" not in html


def test_portal_page_has_theme_toggle_and_bootstrap(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert html.count('class="nav-theme-toggle"') == 2
    assert 'data-theme-toggle' in html
    assert "portal-theme" in html
    assert 'data-theme' in html


def test_portal_serves_and_bootstraps_webmcp_progressive_enhancement(tmp_path):
    client, _, _ = _client(tmp_path)

    script = client.get("/portal/static/portal_webmcp.js")
    html = client.get("/portal").text

    assert script.status_code == 200
    assert "javascript" in script.headers.get("content-type", "")
    assert 'src="/portal/static/portal_webmcp.js"' in html
    assert "function getPortalWorkingContext()" in html
    assert "VansPortalWebMcp.enhance" in html
    assert html.index("const me = await api('/auth/me')") < html.index("enhancePortalWithWebMcp();")


def test_portal_catalog_modal_uses_structured_fields(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert 'id="catalogFormRoot"' in html
    assert 'id="catalogActionsList"' in html
    assert 'id="catalogSnippetsList"' in html
    assert 'id="editCatalogYaml"' not in html
    assert "onEditCatalogBackdropClick" not in html
    assert "js-yaml" in html


def test_portal_catalog_modal_edits_actions_and_snippets_as_tabs(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert html.index('id="catalogDropzone"') < html.index('id="catalogFormRoot"')
    assert html.index('id="catalogFormRoot"') < html.index('id="catalogSaveMsg"')
    assert 'id="catalogActionsTab"' in html
    assert 'id="catalogSnippetsTab"' in html
    assert 'id="catalogActionsTabCount"' in html
    assert 'id="catalogSnippetsTabCount"' in html
    assert 'id="catalogActionsPanel"' in html
    assert 'id="catalogSnippetsPanel"' in html
    assert 'id="catalogAddActionBtn"' in html
    assert 'id="catalogAddSnippetBtn"' in html
    assert 'class="catalog-section-title"' not in html
    assert "showCatalogEditorTab('actions')" in html
    assert "showCatalogEditorTab('snippets')" in html
    assert 'id="catalogSnippetsPanel" class="catalog-tab-panel hidden"' in html
    assert 'id="catalogActionsTab" class="tab-active"' in html or 'class="tab-active" id="catalogActionsTab"' in html


def test_portal_session_row_shows_occupied_nickname_seats_versus_limit(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert "<th>暱稱座位</th>" in html
    assert "sessionSeatLimitCell" in html
    assert "beginEditSessionSeatLimit" in html
    assert "nickname_seat_count" in html
    assert "seat_limit" in html
    assert '{"seat_limit"' in html or "{ seat_limit" in html


def test_portal_css_defines_light_and_dark_themes(tmp_path):
    client, _, _ = _client(tmp_path)
    css = client.get("/portal/static/portal.css").text
    assert "--accent: #007070" in css
    assert "--bg-base: #f3f7f7" in css
    assert "--code-text: #0f172a" in css
    assert 'data-theme="dark"' in css
    assert "--accent: #4f46e5" in css
    assert "--bg-base: #020617" in css
    assert "--code-text: #d7f5e9" in css
    assert "color: var(--code-text)" in css
    assert "color: #d7f5e9" not in css


def test_portal_css_error_uses_theme_tokens_with_readable_light_contrast(tmp_path):
    client, _, _ = _client(tmp_path)
    css = client.get("/portal/static/portal.css").text
    assert "--error-fg:" in css
    assert "--error-bg:" in css
    assert "--error-border:" in css
    error_rule = re.search(r"(?m)^\s*\.error\s*\{([^}]+)\}", css)
    assert error_rule, "missing .error rule"
    body = error_rule.group(1)
    assert "color: var(--error-fg)" in body
    assert "background: var(--error-bg)" in body
    assert "border:" in body and "var(--error-border)" in body
    # Light Theme must not keep the dark-oriented pale pink text.
    assert re.search(r"(?m)^\s*:root\s*\{[^}]*--error-fg:\s*#b91c1c", css, re.S)
    assert "#fca5a5" not in re.search(r"(?m)^\s*:root\s*\{([^}]+)\}", css, re.S).group(1)


def test_portal_page_has_collapsible_active_keys_section(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert 'id="activeKeysSection"' in html
    assert "toggleActiveKeys" in html
    assert 'aria-expanded="false"' in html
    assert "有效 Key" in html
    css = client.get("/portal/static/portal.css").text
    assert "max-height: 240px" in css
    assert ".active-keys-section.is-collapsed" in css or ".is-collapsed" in css


def test_portal_page_has_device_session_management(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert 'id="deviceSessions"' in html
    assert "/auth/sessions/revoke-others" in html
    assert "revokeDeviceSession" in html


def test_portal_oauth_btn_matches_primary_in_light_keeps_white_in_dark(tmp_path):
    client, _, _ = _client(tmp_path)
    css = client.get("/portal/static/portal.css").text
    light = re.search(r"(?m)^\s*\.oauth-btn\s*\{([^}]+)\}", css)
    light_hover = re.search(r"(?m)^\s*\.oauth-btn:hover\s*\{([^}]+)\}", css)
    dark = re.search(
        r'(?m)^\s*html\[data-theme="dark"\]\s*\.oauth-btn\s*\{([^}]+)\}', css
    )
    dark_hover = re.search(
        r'(?m)^\s*html\[data-theme="dark"\]\s*\.oauth-btn:hover\s*\{([^}]+)\}',
        css,
    )
    assert light, "missing .oauth-btn rule"
    assert light_hover, "missing .oauth-btn:hover rule"
    assert "background: var(--accent)" in light.group(1)
    assert "color: white" in light.group(1)
    assert "box-shadow: var(--btn-shadow)" in light.group(1)
    assert "background: var(--accent-hover)" in light_hover.group(1)
    assert "transform: translateY(-2px)" in light_hover.group(1)
    assert dark, 'missing html[data-theme="dark"] .oauth-btn rule'
    assert dark_hover, 'missing html[data-theme="dark"] .oauth-btn:hover rule'
    assert "background: white" in dark.group(1)
    assert "color: #0f172a" in dark.group(1)
    assert "background: #eef2ff" in dark_hover.group(1)


def test_portal_login_network_uses_theme_aware_colors(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert 'id="loginNetworkRoot"' in html
    assert "themeLook" in html
    assert "ShaderMaterial" in html
    assert "prefers-reduced-motion" in html
    # Light Theme Login Network: brighter cyan-teal on light field
    assert "g: 0.92" in html
    assert "intensity: 1.65" in html
    # Dark Theme Login Network: white / full tint
    assert "r: 1.0, g: 1.0, b: 1.0" in html


def test_dev_google_login_works_when_oauth_disabled(tmp_path):
    client, repo, _ = _client(tmp_path)
    response = client.post("/auth/google", json={"email": "student@gmail.com", "name": "Student"})
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["email"] == "student@gmail.com"
    token = response.cookies.get("vcr_portal_session")
    assert token
    session = repo.authenticate_portal_session(token)
    assert session is not None
    assert session.user_id == user["id"]
    assert response.cookies.get("session_user_id") is None
    assert repo.get_user_by_email("student@gmail.com") is not None


def test_login_stores_normalized_browser_description(tmp_path):
    client, repo, _ = _client(tmp_path)
    response = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student"},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/123.0"},
    )
    session = repo.authenticate_portal_session(response.cookies.get("vcr_portal_session"))
    assert session is not None
    assert session.browser_description == "Chrome on Windows"


def test_https_portal_uses_host_prefixed_secure_cookie(tmp_path):
    settings = _settings(
        tmp_path,
        google_client_id="cid",
        google_client_secret="csecret",
        dev_auth_enabled=False,
    )
    settings = replace(settings, public_url="https://portal.example.com")
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    app.include_router(create_portal_router(PortalUseCase(repo, settings), settings))
    client = TestClient(app, base_url=settings.public_url)
    oauth = GoogleOAuthService(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="https://portal.example.com/auth/google/callback",
        session_secret=settings.auth.session_secret,
    )
    state = oauth.create_state()
    claims = GoogleUserClaims(email="student@gmail.com", name="Student", google_sub="sub")

    with patch(
        "src.presentation.fastapi.routers.portal_router.GoogleOAuthService.exchange_code",
        new=AsyncMock(return_value=claims),
    ):
        response = client.get(
            f"/auth/google/callback?code=fake&state={state}",
            cookies={"oauth_state": state},
            follow_redirects=False,
        )

    cookie = response.headers.get("set-cookie") or ""
    assert "__Host-vcr_portal_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie


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
    token = response.cookies.get("vcr_portal_session")
    assert token
    assert token != "1"
    session = repo.authenticate_portal_session(token)
    assert session is not None
    assert session.user_id == 1
    assert response.cookies.get("session_user_id") is None
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


def test_auth_me_rejects_forged_legacy_user_id_cookie(tmp_path):
    client, repo, _ = _client(tmp_path)
    user = repo.upsert_google_user("student@example.com", "Student")

    response = client.get(
        "/auth/me",
        cookies={"session_user_id": str(user["id"])},
    )

    assert response.status_code == 401


def test_auth_me_accepts_server_issued_portal_session(tmp_path):
    client, repo, _ = _client(tmp_path)
    user = repo.upsert_google_user("student@example.com", "Student")
    token, _ = repo.create_portal_session(user["id"], "Test browser")

    response = client.get(
        "/auth/me",
        cookies={"vcr_portal_session": token},
    )

    assert response.status_code == 200
    assert response.json()["id"] == user["id"]


def test_logout_revokes_current_portal_session(tmp_path):
    client, repo, _ = _client(tmp_path)
    user = repo.upsert_google_user("student@example.com", "Student")
    token, _ = repo.create_portal_session(user["id"], "Test browser")
    client.cookies.set("vcr_portal_session", token)

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert repo.authenticate_portal_session(token) is None
    assert client.get("/auth/me").status_code == 401


def test_user_can_list_and_revoke_another_signed_in_device(tmp_path):
    client, repo, _ = _client(tmp_path)
    user = repo.upsert_google_user("student@example.com", "Student")
    current_token, current = repo.create_portal_session(user["id"], "Current browser")
    other_token, other = repo.create_portal_session(user["id"], "Other browser")
    client.cookies.set("vcr_portal_session", current_token)

    listing = client.get("/auth/sessions")
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()["items"]} == {
        current.session_id,
        other.session_id,
    }
    assert next(item for item in listing.json()["items"] if item["current"])["id"] == current.session_id

    revoked = client.delete(f"/auth/sessions/{other.session_id}")
    assert revoked.status_code == 200
    assert repo.authenticate_portal_session(other_token) is None
    assert repo.authenticate_portal_session(current_token) is not None


def test_user_can_revoke_every_other_signed_in_device(tmp_path):
    client, repo, _ = _client(tmp_path)
    user = repo.upsert_google_user("student@example.com", "Student")
    current_token, current = repo.create_portal_session(user["id"], "Current browser")
    other_tokens = [
        repo.create_portal_session(user["id"], f"Other browser {index}")[0]
        for index in range(2)
    ]
    client.cookies.set("vcr_portal_session", current_token)

    response = client.post("/auth/sessions/revoke-others")

    assert response.status_code == 200
    assert response.json() == {"revoked": 2}
    assert repo.authenticate_portal_session(current_token) is not None
    assert all(repo.authenticate_portal_session(token) is None for token in other_tokens)
    assert [item["id"] for item in repo.list_portal_sessions(user["id"])] == [current.session_id]


def test_admin_endpoint_rejects_forged_legacy_admin_cookie(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")

    response = client.get(
        "/admin/users",
        cookies={"session_user_id": str(admin["id"])},
    )

    assert response.status_code == 401


def test_admin_endpoint_accepts_server_issued_portal_session(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    token, _ = repo.create_portal_session(admin["id"], "Test browser")

    response = client.get(
        "/admin/users",
        cookies={"vcr_portal_session": token},
    )

    assert response.status_code == 200


def test_admin_mutation_rejects_cross_site_origin(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    student = repo.upsert_google_user("student@example.com", "Student")

    response = client.patch(
        f"/admin/users/{student['id']}",
        cookies=_portal_cookie(repo, admin),
        headers={"Origin": "https://evil.example"},
        json={"status": "inactive"},
    )

    assert response.status_code == 403
    assert repo.get_user(student["id"])["status"] == "active"


def test_portal_permission_error_returns_403(tmp_path):
    client, repo, _ = _client(tmp_path)
    student = repo.upsert_google_user("student@example.com", "Student")

    response = client.get("/admin/users", cookies=_portal_cookie(repo, student))

    assert response.status_code == 403
    assert response.json()["detail"] == "權限不足"


def test_dev_google_login_requires_explicit_enablement(tmp_path):
    client, _, _ = _client(tmp_path, dev_auth_enabled=False)

    response = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student"},
    )

    assert response.status_code == 403


def test_dev_google_login_requires_loopback_request_host(tmp_path):
    client, _, _ = _client(tmp_path, base_url="http://public.example")

    response = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student"},
    )

    assert response.status_code == 403


def test_admin_archive_run_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")

    response = client.post("/admin/archive/run", cookies=_portal_cookie(repo, admin))

    assert response.status_code == 200
    assert response.json() == {"archived": 0, "deleted": 0}


def test_admin_update_settings_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")

    response = client.patch(
        "/admin/settings",
        cookies=_portal_cookie(repo, admin),
        json={
            "archive_after_days": 10,
            "delete_after_days": 20,
            "student_default_ttl_hours": 4,
            "open_registration": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["prompt_logs"]["archive_after_days"] == 10
    assert payload["prompt_logs"]["delete_after_days"] == 20
    assert payload["student_default_ttl_hours"] == 4
    assert payload["auth"]["open_registration"] is False
    assert repo.get_runtime_settings()["archive_after_days"] == "10"
    assert repo.get_runtime_settings()["delete_after_days"] == "20"


def test_admin_clear_archive_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    ended = repo.create_class(teacher["id"], "Ended", None, 2)
    session = repo.create_class_session(ended["id"], teacher["id"], "Session")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    context = repo.verify_api_key_context(key)
    assert context is not None
    repo.log_prompt(context, "ended log", "ended log", "fake-model", "ok", None)
    repo.set_class_status(ended["id"], "ended")
    repo.archive_prompt_logs()

    response = client.post(
        "/admin/archive/clear",
        cookies=_portal_cookie(repo, admin),
    )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1


def test_admin_prompt_log_usage_and_delete_by_user(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    user_a = repo.upsert_google_user("a@example.com", "A")
    user_b = repo.upsert_google_user("b@example.com", "B")
    klass = repo.create_class(teacher["id"], "Class", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    key_a = repo.redeem_invite(session["invite_code"], user_a["id"])["api_key"]
    key_b = repo.redeem_invite(session["invite_code"], user_b["id"])["api_key"]
    ctx_a = repo.verify_api_key_context(key_a)
    ctx_b = repo.verify_api_key_context(key_b)
    assert ctx_a is not None and ctx_b is not None
    repo.log_prompt(ctx_a, "a log", "a log", "fake-model", "ok", None)
    repo.log_prompt(ctx_b, "b log", "b log", "fake-model", "ok", None)

    forbidden = client.get(
        "/admin/prompt-logs/usage",
        cookies=_portal_cookie(repo, teacher),
    )
    assert forbidden.status_code == 403

    usage_response = client.get(
        "/admin/prompt-logs/usage",
        cookies=_portal_cookie(repo, admin),
    )
    assert usage_response.status_code == 200
    usage = {item["user_id"]: item for item in usage_response.json()["items"]}
    assert usage[user_a["id"]]["live_count"] == 1
    assert usage[user_b["id"]]["live_count"] == 1

    empty = client.post(
        "/admin/prompt-logs/delete",
        cookies=_portal_cookie(repo, admin),
        json={"user_ids": []},
    )
    assert empty.status_code == 400

    delete_response = client.post(
        "/admin/prompt-logs/delete",
        cookies=_portal_cookie(repo, admin),
        json={"user_ids": [user_a["id"]]},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted_live": 1, "deleted_archive": 0}

    remaining = repo.list_prompt_logs(teacher["id"], klass["id"])
    assert [row["raw_prompt"] for row in remaining] == ["b log"]


def test_admin_update_user_roles_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    student = repo.upsert_google_user("student@example.com", "Student")

    response = client.patch(
        f"/admin/users/{student['id']}",
        cookies=_portal_cookie(repo, admin),
        json={"roles": ["student", "teacher"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["roles"]) == {"student", "teacher"}


def test_admin_update_user_status_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    student = repo.upsert_google_user("student@example.com", "Student")

    response = client.patch(
        f"/admin/users/{student['id']}",
        cookies=_portal_cookie(repo, admin),
        json={"status": "inactive"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "inactive"


def test_admin_update_class_endpoint(tmp_path):
    client, repo, _ = _client(tmp_path)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)

    response = client.patch(
        f"/admin/classes/{klass['id']}",
        cookies=_portal_cookie(repo, admin),
        json={"status": "ended"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ended"


def test_prompt_logs_endpoint_returns_preview_without_raw_prompt(tmp_path):
    from src.domain.entities.auth import AuthContext

    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    auth_context = AuthContext(
        user_id=teacher["id"],
        email=teacher["email"],
        name=teacher["name"],
        class_id=klass["id"],
    )
    repo.log_prompt(
        auth=auth_context,
        raw_prompt="user: <userRequest>hello portal</userRequest>",
        final_prompt="user: <userRequest>hello portal</userRequest>",
        model="openrouter@test",
        status="ok",
        client_ip="127.0.0.1",
        message_preview="hello portal",
        response_preview="assistant reply",
        api_endpoint="/v1/responses",
        messages_json='[{"role":"user","content":"<userRequest>hello portal</userRequest>"},{"role":"assistant","content":"assistant reply"}]',
    )

    response = client.get(
        f"/teacher/classes/{klass['id']}/prompt-logs",
        cookies=_portal_cookie(repo, teacher),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 10
    assert payload["has_filter"] is False
    assert payload["items"][0]["message_preview"] == "hello portal"
    assert payload["items"][0]["response_preview"] == "assistant reply"
    assert payload["items"][0]["api_endpoint"] == "/v1/responses"
    assert "raw_prompt" not in payload["items"][0]


def test_prompt_logs_can_filter_by_session_id(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session_a = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    session_b = repo.create_class_session(klass["id"], teacher["id"], "第二堂")
    context_a = repo.verify_api_key_context(repo.redeem_invite(session_a["invite_code"], student["id"])["api_key"])
    context_b = repo.verify_api_key_context(repo.redeem_invite(session_b["invite_code"], student["id"])["api_key"])
    assert context_a is not None and context_b is not None

    repo.log_prompt(
        auth=context_a,
        raw_prompt="session a",
        final_prompt="session a",
        model="openrouter@test",
        status="ok",
        client_ip="127.0.0.1",
        message_preview="from session a",
    )
    repo.log_prompt(
        auth=context_b,
        raw_prompt="session b",
        final_prompt="session b",
        model="openrouter@test",
        status="ok",
        client_ip="127.0.0.1",
        message_preview="from session b",
    )

    cookies = _portal_cookie(repo, teacher)
    filtered = client.get(
        f"/teacher/classes/{klass['id']}/prompt-logs",
        params={"session_id": session_a["id"]},
        cookies=cookies,
    )

    assert filtered.status_code == 200
    payload = filtered.json()
    assert payload["has_filter"] is True
    assert len(payload["items"]) == 1
    assert payload["items"][0]["message_preview"] == "from session a"
    assert payload["items"][0]["session_id"] == session_a["id"]


def test_prompt_log_detail_endpoint(tmp_path):
    from src.domain.entities.auth import AuthContext

    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    auth_context = AuthContext(
        user_id=teacher["id"],
        email=teacher["email"],
        name=teacher["name"],
        class_id=klass["id"],
    )
    repo.log_prompt(
        auth=auth_context,
        raw_prompt="ignored",
        final_prompt="ignored",
        model="openrouter@test",
        status="ok",
        client_ip="127.0.0.1",
        message_preview="detail me",
        response_preview="agent says hi",
        api_endpoint="/v1/chat/completions",
        messages_json='[{"role":"user","content":"detail me"},{"role":"assistant","content":"agent says hi"}]',
    )
    log_id = repo.list_prompt_logs(teacher["id"], klass["id"], limit=1)[0]["id"]

    response = client.get(
        f"/teacher/classes/{klass['id']}/prompt-logs/{log_id}",
        cookies=_portal_cookie(repo, teacher),
    )

    assert response.status_code == 200
    assert response.json() == {
        "messages": [
            {"role": "user", "content": "detail me"},
            {"role": "assistant", "content": "agent says hi"},
        ],
        "api_endpoint": "/v1/chat/completions",
        "response_preview": "agent says hi",
    }


def test_list_classes_requires_teacher_and_returns_owned_classes(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")
    owned = repo.create_class(teacher["id"], "AI 素養", None, 2)

    response = client.get("/teacher/classes", cookies=_portal_cookie(repo, teacher))
    forbidden = client.get("/teacher/classes", cookies=_portal_cookie(repo, student))

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == owned["id"]
    assert forbidden.status_code == 403


def test_list_and_create_class_sessions(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    cookies = _portal_cookie(repo, teacher)
    session_at = "2026-06-21T14:00:00+00:00"

    create = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "第一堂", "session_at": session_at, "ttl_hours": 3},
    )
    assert create.status_code == 200
    created = create.json()
    assert created["session_at"] == session_at
    assert created["name"] == "第一堂"
    assert created["expires_at"] == "2026-06-21T17:00:00+00:00"

    listing = client.get(f"/teacher/classes/{klass['id']}/sessions", cookies=cookies)
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1
    assert listing.json()["items"][0]["invite_code"]
    assert listing.json()["items"][0]["name"] == "第一堂"

    patch = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{created['id']}",
        cookies=cookies,
        json={"name": "第二堂"},
    )
    assert patch.status_code == 200
    assert patch.json()["name"] == "第二堂"


def test_get_class_session_enforces_portal_authorization_and_missing_target(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    other = repo.upsert_google_user("other@school.edu", "Other")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")

    found = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher),
    )
    unauthenticated = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}"
    )
    forbidden = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, other),
    )
    missing = client.get(
        f"/teacher/classes/{klass['id']}/sessions/999999",
        cookies=_portal_cookie(repo, teacher),
    )

    assert found.status_code == 200
    assert found.json()["id"] == session["id"]
    assert found.json()["class_id"] == klass["id"]
    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert missing.status_code == 404


def test_read_only_class_session_and_usage_http_contracts(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    teacher_cookie = _portal_cookie(repo, teacher)
    student_cookie = _portal_cookie(repo, student)

    sessions = client.get(
        f"/teacher/classes/{klass['id']}/sessions", cookies=teacher_cookie
    )
    usage = client.get(f"/teacher/classes/{klass['id']}/usage", cookies=teacher_cookie)

    assert sessions.status_code == 200
    assert sessions.json()["items"][0]["id"] == session["id"]
    assert usage.status_code == 200
    assert usage.json() == {"items": []}

    for path in (
        f"/teacher/classes/{klass['id']}/sessions",
        f"/teacher/classes/{klass['id']}/usage",
    ):
        assert client.get(path).status_code == 401
        assert client.get(path, cookies=student_cookie).status_code == 403

    validation = client.get("/teacher/classes/not-an-id/sessions", cookies=teacher_cookie)
    assert validation.status_code == 422


def test_new_class_session_has_seat_limit_60(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    cookies = _portal_cookie(repo, teacher)

    created = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "第一堂", "ttl_hours": 2},
    )
    listing = client.get(f"/teacher/classes/{klass['id']}/sessions", cookies=cookies)

    assert created.status_code == 200
    assert created.json()["seat_limit"] == 60
    assert listing.json()["items"][0]["seat_limit"] == 60
    assert listing.json()["items"][0]["nickname_seat_count"] == 0


def test_owner_and_admin_can_change_session_seat_limit(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    admin = repo.upsert_google_user("admin@school.edu", "Admin")
    other = repo.upsert_google_user("other@school.edu", "Other")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    teacher_cookies = _portal_cookie(repo, teacher)
    admin_cookies = _portal_cookie(repo, admin)
    other_cookies = _portal_cookie(repo, other)

    by_owner = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=teacher_cookies,
        json={"seat_limit": 12},
    )
    assert by_owner.status_code == 200
    assert by_owner.json()["seat_limit"] == 12

    by_admin = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=admin_cookies,
        json={"seat_limit": 8},
    )
    assert by_admin.status_code == 200
    assert by_admin.json()["seat_limit"] == 8

    listing = client.get(f"/teacher/classes/{klass['id']}/sessions", cookies=teacher_cookies)
    assert listing.json()["items"][0]["seat_limit"] == 8

    forbidden = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=other_cookies,
        json={"seat_limit": 99},
    )
    assert forbidden.status_code == 403


def test_session_seat_limit_rejects_non_positive_values(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    cookies = _portal_cookie(repo, teacher)

    zero = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
        json={"seat_limit": 0},
    )
    negative = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
        json={"seat_limit": -1},
    )

    assert zero.status_code == 400
    assert zero.json()["detail"] == "座位上限必須為正整數"
    assert negative.status_code == 400
    assert negative.json()["detail"] == "座位上限必須為正整數"


def test_session_image_generation_toggle(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    cookies = _portal_cookie(repo, teacher)

    create = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "第一堂", "ttl_hours": 2},
    )
    session_id = create.json()["id"]
    assert repo.is_image_generation_enabled(session_id) is True

    disable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"image_generation_enabled": False},
    )
    assert disable.status_code == 200
    assert repo.is_image_generation_enabled(session_id) is False

    enable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"image_generation_enabled": True},
    )
    assert enable.status_code == 200
    assert repo.is_image_generation_enabled(session_id) is True


def test_session_tts_toggle(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    cookies = _portal_cookie(repo, teacher)

    create = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "第一堂", "ttl_hours": 2},
    )
    session_id = create.json()["id"]
    assert repo.is_tts_enabled(session_id) is True

    disable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"tts_enabled": False},
    )
    assert disable.status_code == 200
    assert repo.is_tts_enabled(session_id) is False

    enable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"tts_enabled": True},
    )
    assert enable.status_code == 200
    assert repo.is_tts_enabled(session_id) is True


def test_session_speech_transcription_toggle(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    cookies = _portal_cookie(repo, teacher)

    create = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "第一堂", "ttl_hours": 2},
    )
    session_id = create.json()["id"]
    assert repo.is_speech_transcription_enabled(session_id) is False

    enable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"speech_transcription_enabled": True},
    )
    assert enable.status_code == 200
    assert repo.is_speech_transcription_enabled(session_id) is True

    disable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"speech_transcription_enabled": False},
    )
    assert disable.status_code == 200
    assert repo.is_speech_transcription_enabled(session_id) is False


def test_session_prompt_logging_toggle(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    cookies = _portal_cookie(repo, teacher)

    create = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "第一堂", "ttl_hours": 2},
    )
    session_id = create.json()["id"]
    assert repo.is_prompt_logging_enabled(session_id) is True

    disable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"prompt_logging_enabled": False},
    )
    assert disable.status_code == 200
    assert repo.is_prompt_logging_enabled(session_id) is False

    enable = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"prompt_logging_enabled": True},
    )
    assert enable.status_code == 200
    assert repo.is_prompt_logging_enabled(session_id) is True


def test_install_vscode_models_download_requires_login(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/portal/download/install-vscode-models.ps1")
    assert response.status_code == 401


def test_install_vscode_models_download_returns_script(tmp_path):
    client, repo, _ = _client(tmp_path)
    student = repo.upsert_google_user("student@example.com", "Student")
    response = client.get(
        "/portal/download/install-vscode-models.ps1",
        cookies=_portal_cookie(repo, student),
    )
    assert response.status_code == 200
    assert "install-vscode-models.ps1" in response.headers["content-disposition"]
    assert "VCRouter" in response.text
    assert "Merge-ChatLanguageModels" in response.text


def test_install_vscode_models_zip_download(tmp_path):
    client, repo, _ = _client(tmp_path)
    student = repo.upsert_google_user("student@example.com", "Student")
    response = client.get(
        "/portal/download/install-vscode-models.zip",
        cookies=_portal_cookie(repo, student),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "install-vscode-models.zip" in response.headers["content-disposition"]
    assert response.content[:2] == b"PK"


def test_install_vscode_models_cmd_download(tmp_path):
    client, repo, _ = _client(tmp_path)
    student = repo.upsert_google_user("student@example.com", "Student")
    response = client.get(
        "/portal/download/install-vscode-models.cmd",
        cookies=_portal_cookie(repo, student),
    )
    assert response.status_code == 200
    assert "install-vscode-models.cmd" in response.headers["content-disposition"]
    assert "ExecutionPolicy Bypass" in response.text


def test_install_vscode_models_command_download_requires_login(tmp_path):
    client, _, _ = _client(tmp_path)
    response = client.get("/portal/download/install-vscode-models.command")
    assert response.status_code == 401


def test_install_vscode_models_command_download(tmp_path):
    client, repo, _ = _client(tmp_path)
    student = repo.upsert_google_user("student@example.com", "Student")
    response = client.get(
        "/portal/download/install-vscode-models.command",
        cookies=_portal_cookie(repo, student),
    )
    assert response.status_code == 200
    assert "install-vscode-models.command" in response.headers["content-disposition"]
    assert response.text.startswith("#!/bin/bash")
    assert "python3" in response.text


def test_owner_and_admin_can_end_session_and_edit_expires(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    admin = repo.upsert_google_user("admin@school.edu", "Admin")
    other = repo.upsert_google_user("other@school.edu", "Other")
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    teacher_cookies = _portal_cookie(repo, teacher)
    admin_cookies = _portal_cookie(repo, admin)
    other_cookies = _portal_cookie(repo, other)

    end = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=teacher_cookies,
        json={"status": "ended"},
    )
    assert end.status_code == 200
    assert end.json()["status"] == "ended"
    assert end.json()["expires_at"]

    reopen_without_expires = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=admin_cookies,
        json={"status": "active"},
    )
    assert reopen_without_expires.status_code == 400

    expires = "2026-12-31T15:00:00+00:00"
    patch_expires = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=admin_cookies,
        json={"expires_at": expires},
    )
    assert patch_expires.status_code == 200
    assert patch_expires.json()["expires_at"].startswith("2026-12-31T15:00:00")
    assert patch_expires.json()["status"] == "active"

    listing = client.get(f"/teacher/classes/{klass['id']}/sessions", cookies=admin_cookies)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["status"] == "active"

    forbidden = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=other_cookies,
        json={"status": "ended"},
    )
    assert forbidden.status_code == 403


class _FakePoolGateway:
    def __init__(self):
        self.released: list[tuple[str, int]] = []

    def pool_status(self, *, limited_only: bool = True):
        return {
            "providers": {
                "ollama_cloud": {
                    "pool": {
                        "key_count": 2,
                        "max_concurrent_per_key": 3,
                        "capacity": 6,
                        "in_flight_total": 3,
                        "waiting": 0,
                        "busy_total": 1,
                        "keys": [
                            {
                                "index": 0,
                                "label": "OLLAMA_CLOUD 1",
                                "in_flight": 2,
                                "cap": 3,
                                "quarantined": True,
                                "quarantine_remaining_sec": 1200.0,
                            },
                            {
                                "index": 1,
                                "label": "OLLAMA_CLOUD 2",
                                "in_flight": 1,
                                "cap": 3,
                                "quarantined": False,
                                "quarantine_remaining_sec": None,
                            },
                        ],
                    }
                }
            }
        }

    async def release_key_quarantine(self, provider: str, index: int) -> None:
        self.released.append((provider, index))


def test_teacher_upstream_pools_returns_limited_providers(tmp_path):
    client, repo, _ = _client(tmp_path, llm_gateway=_FakePoolGateway())
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    response = client.get("/teacher/upstream-pools", cookies=_portal_cookie(repo, teacher))
    assert response.status_code == 200
    payload = response.json()
    assert set(payload["providers"]) == {"ollama_cloud"}
    keys = payload["providers"]["ollama_cloud"]["pool"]["keys"]
    assert [item["label"] for item in keys] == ["OLLAMA_CLOUD 1", "OLLAMA_CLOUD 2"]
    assert keys[0]["quarantined"] is True
    assert keys[0]["quarantine_remaining_sec"] == 1200.0


def test_student_upstream_pools_forbidden(tmp_path):
    client, repo, _ = _client(tmp_path, llm_gateway=_FakePoolGateway())
    student = repo.upsert_google_user("student@gmail.com", "Student")
    response = client.get("/teacher/upstream-pools", cookies=_portal_cookie(repo, student))
    assert response.status_code == 403


def test_teacher_can_release_key_quarantine(tmp_path):
    gateway = _FakePoolGateway()
    client, repo, _ = _client(tmp_path, llm_gateway=gateway)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    response = client.post(
        "/teacher/upstream-pools/ollama_cloud/keys/0/quarantine-release",
        cookies=_portal_cookie(repo, teacher),
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "provider": "ollama_cloud", "index": 0}
    assert gateway.released == [("ollama_cloud", 0)]


def test_student_cannot_release_key_quarantine(tmp_path):
    client, repo, _ = _client(tmp_path, llm_gateway=_FakePoolGateway())
    student = repo.upsert_google_user("student@gmail.com", "Student")
    response = client.post(
        "/teacher/upstream-pools/ollama_cloud/keys/0/quarantine-release",
        cookies=_portal_cookie(repo, student),
    )
    assert response.status_code == 403
