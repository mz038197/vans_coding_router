"""The router as the OAuth authorization server, over HTTP (ADR 0094)."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.oauth_use_case import OAuthUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.auth.oauth_signing import load_oauth_signing_key
from src.infrastructure.config import (
    AuthSettings,
    DatabaseSettings,
    OAuthClientSettings,
    OAuthSettings,
    RouterSettings,
)
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.oauth_router import create_oauth_router
from src.presentation.fastapi.routers.portal_router import create_portal_router

PUBLIC_URL = "http://testserver"
AGENT_CALLBACK = "https://agent.example/oauth/callback"
BOOKING_CALLBACK = "https://booking.example/auth/callback"
AGENT_SECRET = "agent-builder-secret"

_PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode("ascii")
)


def _settings(tmp_path) -> RouterSettings:
    return RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url=PUBLIC_URL,
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@gmail.com",),
            session_secret="test-session-secret",
            dev_auth_enabled=True,
        ),
        oauth=OAuthSettings(
            clients={
                "agent-builder": OAuthClientSettings(
                    client_id="agent-builder",
                    name="Agent Builder",
                    redirect_uris=(AGENT_CALLBACK,),
                    scopes=("classroom",),
                    client_secret_sha256=hashlib.sha256(AGENT_SECRET.encode()).hexdigest(),
                ),
                "env-client": OAuthClientSettings(
                    client_id="env-client",
                    redirect_uris=(AGENT_CALLBACK,),
                    scopes=("classroom",),
                    client_secret_env="TEST_OAUTH_ENV_CLIENT_SECRET",
                ),
                "club-booking-admin": OAuthClientSettings(
                    client_id="club-booking-admin",
                    name="社團預約板",
                    redirect_uris=(BOOKING_CALLBACK,),
                    scopes=("openid", "teacher"),
                ),
            }
        ),
    )


class Harness:
    def __init__(self, tmp_path, *, google: bool = False):
        self.settings = _settings(tmp_path)
        if google:
            self.settings = replace(
                self.settings,
                auth=replace(self.settings.auth, google_client_id="gid", google_client_secret="gsecret"),
            )
        self.repo = SqliteRouterRepository(self.settings.database.path, self.settings)
        portal = PortalUseCase(self.repo, self.settings)
        self.clock_offset = timedelta(0)
        oauth = OAuthUseCase(
            self.repo,
            portal,
            self.settings,
            load_oauth_signing_key(_PEM),
            clock=lambda: datetime.now(UTC) + self.clock_offset,
        )
        app = FastAPI()
        app.include_router(create_portal_router(portal, self.settings))
        app.include_router(create_oauth_router(oauth, self.settings))
        self.client = TestClient(
            app,
            base_url=PUBLIC_URL,
            headers={"Origin": PUBLIC_URL},
            follow_redirects=False,
        )

    def live_session(self, **changes):
        teacher = self.repo.upsert_google_user("teacher@school.edu", "Teacher")
        klass = self.repo.create_class(teacher["id"], "Demo", None)
        session = self.repo.create_class_session(klass["id"], teacher["id"], "Week 1")
        if changes:
            session = self.repo.update_class_session(klass["id"], session["id"], **changes)
        return teacher, klass, session

    def sign_in(self, email: str, name: str) -> dict:
        user = self.repo.upsert_google_user(email, name)
        token, _ = self.repo.create_portal_session(user["id"], "Test browser")
        self.client.cookies.set("vcr_portal_session", token)
        return user


def _pkce(seed: bytes = b"v") -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(seed * 40).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


VERIFIER, CHALLENGE = _pkce()


def _authorize_params(client_id="agent-builder", redirect_uri=AGENT_CALLBACK, scope="classroom", **extra):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": "xyz-state",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
    }
    params.update(extra)
    return {k: v for k, v in params.items() if v is not None}


def _query(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def _nickname_post(h: "Harness", invite_code: str, nickname: str = "Ada", **params):
    form = {**_authorize_params(**params), "invite_code": invite_code, "nickname": nickname, "method": "nickname"}
    return h.client.post("/oauth/authorize", data=form)


def _nickname_code(h: "Harness", invite_code: str, nickname: str = "Ada", **params) -> str:
    response = _nickname_post(h, invite_code, nickname, **params)
    assert response.status_code == 303, response.text
    query = _query(response.headers["location"])
    assert query["state"] == "xyz-state"
    return query["code"]


def _token(h: "Harness", code: str, *, verifier=VERIFIER, redirect_uri=AGENT_CALLBACK, auth=("agent-builder", AGENT_SECRET), **extra):
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier}
    data.update(extra)
    return h.client.post("/oauth/token", data=data, auth=auth)


def _b64json(part: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _verify_rs256(token: str, jwks: dict) -> dict:
    header_part, payload_part, signature_part = token.split(".")
    header = _b64json(header_part)
    assert header["alg"] == "RS256"
    jwk = next(k for k in jwks["keys"] if k["kid"] == header["kid"])

    def as_int(value: str) -> int:
        return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")

    public_key = RSAPublicNumbers(as_int(jwk["e"]), as_int(jwk["n"])).public_key()
    signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
    public_key.verify(signature, f"{header_part}.{payload_part}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return _b64json(payload_part)


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path)


# Discovery and keys


@pytest.mark.parametrize("path", ["/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"])
def test_discovery_names_the_endpoints_and_s256(h, path):
    response = h.client.get(path)

    assert response.status_code == 200
    doc = response.json()
    assert doc["issuer"] == PUBLIC_URL
    assert doc["authorization_endpoint"] == f"{PUBLIC_URL}/oauth/authorize"
    assert doc["token_endpoint"] == f"{PUBLIC_URL}/oauth/token"
    assert doc["jwks_uri"] == f"{PUBLIC_URL}/oauth/jwks"
    assert doc["code_challenge_methods_supported"] == ["S256"]
    assert set(doc["token_endpoint_auth_methods_supported"]) == {"none", "client_secret_post", "client_secret_basic"}
    assert {"classroom", "openid", "teacher"} <= set(doc["scopes_supported"])
    assert doc["response_types_supported"] == ["code"]
    assert doc["grant_types_supported"] == ["authorization_code"]
    assert doc["id_token_signing_alg_values_supported"] == ["RS256"]


def test_jwks_serves_only_the_public_signing_key(h):
    response = h.client.get("/oauth/jwks")

    assert response.status_code == 200
    (key,) = response.json()["keys"]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert key["kid"]
    assert "d" not in key and "p" not in key


# Authorization request validation


def test_unknown_client_is_refused_on_the_page_not_redirected(h):
    response = h.client.get("/oauth/authorize", params=_authorize_params(client_id="nobody"))

    assert response.status_code == 400
    assert "location" not in response.headers
    assert "無法完成授權" in response.text


@pytest.mark.parametrize(
    "uri", [AGENT_CALLBACK + "/", AGENT_CALLBACK + "?x=1", "https://evil.example/cb", None]
)
def test_redirect_uri_must_match_exactly_or_the_page_refuses(h, uri):
    response = h.client.get("/oauth/authorize", params=_authorize_params(redirect_uri=uri))

    assert response.status_code == 400
    assert "location" not in response.headers


def test_scope_not_allowed_for_the_client_redirects_invalid_scope(h):
    response = h.client.get("/oauth/authorize", params=_authorize_params(scope="openid teacher"))

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(AGENT_CALLBACK + "?")
    query = _query(location)
    assert query["error"] == "invalid_scope"
    assert query["state"] == "xyz-state"
    assert "code" not in query


def test_unknown_scope_combination_is_invalid_scope(h):
    response = h.client.get(
        "/oauth/authorize",
        params=_authorize_params(client_id="club-booking-admin", redirect_uri=BOOKING_CALLBACK, scope="teacher"),
    )

    assert _query(response.headers["location"])["error"] == "invalid_scope"


@pytest.mark.parametrize(
    "changes",
    [
        {"code_challenge_method": None},
        {"code_challenge_method": "plain"},
        {"code_challenge": None},
        {"code_challenge": "short"},
    ],
)
def test_pkce_s256_is_required(h, changes):
    response = h.client.get("/oauth/authorize", params=_authorize_params(**changes))

    assert response.status_code == 302
    assert _query(response.headers["location"])["error"] == "invalid_request"


def test_response_type_other_than_code_is_unsupported(h):
    response = h.client.get("/oauth/authorize", params=_authorize_params(response_type="token"))

    assert _query(response.headers["location"])["error"] == "unsupported_response_type"


def test_classroom_page_asks_invite_code_then_nickname_or_google(h):
    response = h.client.get("/oauth/authorize", params=_authorize_params())

    assert response.status_code == 200
    page = response.text
    assert page.index('name="invite_code"') < page.index('name="nickname"')
    assert page.index("以暱稱加入") < page.index("改用 Google 帳號加入")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_teacher_page_offers_google_only(h):
    response = h.client.get(
        "/oauth/authorize",
        params=_authorize_params(client_id="club-booking-admin", redirect_uri=BOOKING_CALLBACK, scope="openid teacher"),
    )

    assert response.status_code == 200
    assert "以 Google 帳號登入" in response.text
    assert 'name="nickname"' not in response.text
    assert 'name="invite_code"' not in response.text


# Classroom scope: Nickname Redeem through the page, then the token


def test_nickname_redeem_issues_the_students_classroom_key(h):
    _, klass, session = h.live_session()

    code = _nickname_code(h, session["invite_code"].lower(), "Ada")
    assert "vcr_sk_" not in code
    response = _token(h, code)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "scope"}
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "classroom"
    assert body["access_token"].startswith("vcr_sk_")
    second_redeem = h.client.post(
        "/extension/sessions/nickname-redeem",
        json={"invite_code": session["invite_code"], "nickname": "Ada"},
    )
    assert body["access_token"] == second_redeem.json()["api_key"]
    context = h.repo.verify_api_key_context(body["access_token"])
    assert context.session_id == session["id"] and context.class_id == klass["id"]
    expires_at = datetime.fromisoformat(str(session["expires_at"]).replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    assert abs(body["expires_in"] - (expires_at - datetime.now(UTC)).total_seconds()) <= 2


def test_authorization_redirect_carries_state_and_issuer_and_no_key(h):
    _, _, session = h.live_session()

    response = _nickname_post(h, session["invite_code"], "Ada")

    location = response.headers["location"]
    assert location.startswith(AGENT_CALLBACK + "?")
    assert "vcr_sk_" not in location
    query = _query(location)
    assert set(query) == {"code", "state", "iss"}
    assert query["iss"] == PUBLIC_URL


def test_code_is_single_use(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])

    first = _token(h, code)
    again = _token(h, code)

    assert first.status_code == 200
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"


def test_code_expires_within_a_minute(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])
    h.clock_offset = timedelta(seconds=61)

    response = _token(h, code)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_pkce_verifier_mismatch_is_invalid_grant(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])
    other_verifier, _ = _pkce(b"w")

    response = _token(h, code, verifier=other_verifier)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_missing_verifier_is_invalid_request(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])

    response = _token(h, code, verifier="")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_wrong_redirect_uri_at_the_token_endpoint_is_invalid_grant(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])

    response = _token(h, code, redirect_uri="https://agent.example/other")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_tampered_code_is_invalid_grant(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])
    body, signature = code.split(".")
    payload = _b64json(body)
    payload["u"] = payload["u"] + 1
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode() + "." + signature

    response = _token(h, forged)

    assert response.json()["error"] == "invalid_grant"


def test_client_with_a_secret_must_authenticate(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])

    wrong = _token(h, code, auth=("agent-builder", "wrong"))
    missing = _token(h, code, auth=None, client_id="agent-builder")

    assert wrong.status_code == 401 and wrong.json()["error"] == "invalid_client"
    assert missing.status_code == 401 and missing.json()["error"] == "invalid_client"


def test_client_secret_post_is_accepted(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])

    response = _token(h, code, auth=None, client_id="agent-builder", client_secret=AGENT_SECRET)

    assert response.status_code == 200
    assert response.json()["access_token"].startswith("vcr_sk_")


def test_env_referenced_secret_authenticates_and_unset_env_refuses(h, monkeypatch):
    _, _, session = h.live_session()
    monkeypatch.delenv("TEST_OAUTH_ENV_CLIENT_SECRET", raising=False)
    unset = _token(h, _nickname_code(h, session["invite_code"], client_id="env-client"), auth=("env-client", ""))
    monkeypatch.setenv("TEST_OAUTH_ENV_CLIENT_SECRET", "from-env")

    accepted = _token(h, _nickname_code(h, session["invite_code"], client_id="env-client"), auth=("env-client", "from-env"))

    assert unset.status_code == 401
    assert accepted.status_code == 200


def test_a_code_for_one_client_cannot_be_redeemed_by_another(h):
    _, _, session = h.live_session()
    code = _nickname_code(h, session["invite_code"])

    response = _token(h, code, auth=None, client_id="club-booking-admin")

    assert response.json()["error"] == "invalid_grant"


def test_unsupported_grant_type(h):
    response = h.client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": "x"},
        auth=("agent-builder", AGENT_SECRET),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


def test_nickname_redeem_respects_the_session_seat_limit(h):
    _, _, session = h.live_session(seat_limit=1)
    _nickname_code(h, session["invite_code"], "Ada")

    full = _nickname_post(h, session["invite_code"], "Bob")
    rejoin = _nickname_post(h, session["invite_code"], "Ada")

    assert full.status_code == 400
    assert "location" not in full.headers
    assert "此課堂座位已滿" in full.text
    assert rejoin.status_code == 303


def test_sitting_not_started_shows_its_notice(h):
    starts = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    _, _, session = h.live_session(session_at=starts, expires_at=ends)

    response = _nickname_post(h, session["invite_code"])

    assert response.status_code == 400
    assert "課堂尚未開始" in response.text


def test_ended_sitting_and_bad_invite_show_chinese_notices(h):
    _, klass, session = h.live_session()
    h.repo.update_class_session(
        klass["id"],
        session["id"],
        session_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )

    ended = _nickname_post(h, session["invite_code"])
    bad = _nickname_post(h, "NOPE1234")

    assert "這堂課已結束" in ended.text
    assert "邀請碼無效" in bad.text


def test_page_keeps_what_was_typed_after_a_refusal(h):
    response = _nickname_post(h, "NOPE1234", "Ada<script>")

    assert 'value="NOPE1234"' in response.text
    assert "Ada&lt;script&gt;" in response.text
    assert "<script>" not in response.text


def test_form_post_from_another_origin_is_refused(h):
    _, _, session = h.live_session()
    form = {**_authorize_params(), "invite_code": session["invite_code"], "nickname": "Ada", "method": "nickname"}

    response = h.client.post("/oauth/authorize", data=form, headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert "location" not in response.headers


# The Google path: the page hands off to Google login and resumes afterwards


TEACHER_PARAMS = {"client_id": "club-booking-admin", "redirect_uri": BOOKING_CALLBACK, "scope": "openid teacher"}


def _choose_google(h: Harness, invite_code: str | None = None, **params):
    form = {**_authorize_params(**params), "method": "google"}
    if invite_code is not None:
        form["invite_code"] = invite_code
    return h.client.post("/oauth/authorize", data=form)


def _resume(h: Harness, **query):
    return h.client.get("/oauth/authorize/resume", params=query)


def test_google_choice_goes_to_google_login_for_the_authorization_page(tmp_path):
    h = Harness(tmp_path, google=True)
    _, _, session = h.live_session()

    chosen = _choose_google(h, session["invite_code"])
    login = h.client.get(chosen.headers["location"])

    assert chosen.status_code == 303
    assert chosen.headers["location"] == "/auth/google/login?client=authorize"
    assert "vcr_oauth_pending" in chosen.cookies
    assert session["invite_code"] not in chosen.headers["location"]
    assert login.status_code == 302
    assert login.headers["location"].startswith("https://accounts.google.com/")
    assert login.cookies.get("oauth_client") == "authorize"


def test_google_callback_failure_returns_to_the_authorization_page(tmp_path):
    h = Harness(tmp_path, google=True)
    _, _, session = h.live_session()
    _choose_google(h, session["invite_code"])
    h.client.cookies.set("oauth_client", "authorize")

    callback = h.client.get("/auth/google/callback", params={"error": "access_denied"})
    page = h.client.get(callback.headers["location"])

    assert callback.headers["location"].startswith("/oauth/authorize/resume?login_error=")
    assert page.status_code == 400
    assert "Google 登入已取消" in page.text
    assert f'value="{session["invite_code"]}"' in page.text


def test_google_classroom_redeem_issues_that_users_key(h):
    _, _, session = h.live_session()
    student = h.sign_in("ming@gmail.com", "王小明")

    chosen = _choose_google(h, session["invite_code"])
    resumed = _resume(h)

    assert chosen.headers["location"] == "/oauth/authorize/resume"
    assert resumed.status_code == 302
    query = _query(resumed.headers["location"])
    assert query["state"] == "xyz-state"
    body = _token(h, query["code"]).json()
    context = h.repo.verify_api_key_context(body["access_token"])
    assert context.user_id == student["id"]
    assert context.session_id == session["id"]
    portal_redeem = h.client.post("/sessions/redeem", json={"invite_code": session["invite_code"]})
    assert portal_redeem.json()["api_key"] == body["access_token"]


def test_google_and_nickname_with_the_same_name_are_different_students(h):
    _, _, session = h.live_session()
    h.sign_in("ada@gmail.com", "Ada")
    _choose_google(h, session["invite_code"])
    google_key = _token(h, _query(_resume(h).headers["location"])["code"]).json()["access_token"]

    nickname_key = _token(h, _nickname_code(h, session["invite_code"], "Ada")).json()["access_token"]

    assert google_key != nickname_key
    assert (
        h.repo.verify_api_key_context(google_key).user_id
        != h.repo.verify_api_key_context(nickname_key).user_id
    )


def test_google_redeem_respects_the_session_seat_limit(h):
    _, _, session = h.live_session(seat_limit=1)
    _nickname_code(h, session["invite_code"], "Ada")
    h.sign_in("ming@gmail.com", "王小明")

    _choose_google(h, session["invite_code"])
    resumed = _resume(h)

    assert resumed.status_code == 400
    assert "location" not in resumed.headers
    assert "此課堂座位已滿" in resumed.text


def test_google_choice_needs_the_invite_code_first(h):
    response = _choose_google(h, "")

    assert response.status_code == 400
    assert "請先輸入邀請碼" in response.text
    assert "vcr_oauth_pending" not in response.cookies


def test_resume_without_a_google_login_asks_again(h):
    _, _, session = h.live_session()
    _choose_google(h, session["invite_code"])

    response = _resume(h)

    assert response.status_code == 401
    assert "Google 登入沒有完成" in response.text


def test_resume_without_a_pending_request_is_refused(h):
    h.sign_in("ming@gmail.com", "王小明")

    response = _resume(h)

    assert response.status_code == 400
    assert "location" not in response.headers


# Teacher scope: Google only, teachers and admins only, an ID token and no key


def _teacher_code(h: Harness) -> str:
    _choose_google(h, **TEACHER_PARAMS)
    resumed = _resume(h)
    assert resumed.status_code == 302, resumed.text
    assert resumed.headers["location"].startswith(BOOKING_CALLBACK + "?")
    return _query(resumed.headers["location"])["code"]


def _teacher_token(h: Harness, code: str, **extra):
    return _token(h, code, redirect_uri=BOOKING_CALLBACK, auth=None, client_id="club-booking-admin", **extra)


def test_teacher_signs_in_and_gets_a_signed_id_token(h):
    teacher = h.sign_in("lin@school.edu", "林老師")

    response = _teacher_token(h, _teacher_code(h))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"id_token", "token_type", "expires_in", "scope"}
    assert body["scope"] == "openid teacher"
    assert body["token_type"] == "Bearer"
    claims = _verify_rs256(body["id_token"], h.client.get("/oauth/jwks").json())
    assert claims["iss"] == PUBLIC_URL
    assert claims["aud"] == "club-booking-admin"
    assert claims["sub"] == str(teacher["id"])
    assert claims["name"] == "林老師"
    assert claims["exp"] - claims["iat"] == body["expires_in"]
    assert claims["exp"] > datetime.now(UTC).timestamp()
    assert "vcr_sk_" not in response.text


def test_admin_may_sign_in_with_the_teacher_scope(h):
    admin = h.sign_in("admin@gmail.com", "Admin")

    response = _teacher_token(h, _teacher_code(h))

    claims = _verify_rs256(response.json()["id_token"], h.client.get("/oauth/jwks").json())
    assert claims["sub"] == str(admin["id"])


def test_teacher_scope_refuses_a_student_with_a_clear_page(h):
    h.sign_in("ming@gmail.com", "王小明")
    _choose_google(h, **TEACHER_PARAMS)

    response = _resume(h)

    assert response.status_code == 403
    assert "location" not in response.headers
    assert "此登入僅限教師" in response.text
    assert "王小明" in response.text
    assert "error=access_denied" in response.text


def test_teacher_scope_carries_the_oidc_nonce(h):
    h.sign_in("lin@school.edu", "林老師")
    _choose_google(h, **TEACHER_PARAMS, nonce="n-123")
    code = _query(_resume(h).headers["location"])["code"]

    claims = _b64json(_teacher_token(h, code).json()["id_token"].split(".")[1])

    assert claims["nonce"] == "n-123"


def test_teacher_scope_has_no_nickname_path(h):
    form = {**_authorize_params(**TEACHER_PARAMS), "method": "nickname", "invite_code": "X", "nickname": "Ada"}

    response = h.client.post("/oauth/authorize", data=form)

    assert response.status_code == 400
    assert "location" not in response.headers
