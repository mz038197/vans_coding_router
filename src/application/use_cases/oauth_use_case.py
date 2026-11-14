"""The router as the OAuth authorization server (ADR 0094).

The scope of a request decides what the Authorization Page asks and what the token
endpoint returns:

- `classroom`: an Invite Code, then Nickname Redeem or a Google redeem. The access token
  is that student's Classroom API Key for the sitting, the same key a second redeem
  returns, with `expires_in` up to the sitting's expiry. A refresh token (ADR 0096)
  lasts the sitting too and renews that same key; it is signed, names the client, the
  student and the sitting by id, and never carries a key.
- `openid teacher`: Google only, a teacher or an admin only. The answer is an ID token
  naming the user id and Display Name, and no key.

The authorization code is a signed, 60-second, single-use grant bound to the client,
the redirect URI, the PKCE challenge and the scope. It names the student and the
sitting by integer id; it never carries a key. Single use is recorded in the same
nonce table as Sign-in Handoff, so it holds across machines.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

from src.application.use_cases.portal_use_case import PortalUseCase
from src.domain.ports.router_repository import RouterRepositoryPort
from src.infrastructure.auth.oauth_signing import OAuthSigningKey
from src.infrastructure.config import OAuthClientSettings, RouterSettings
from src.infrastructure.repositories.router_repository_helpers import parse_dt

SCOPE_CLASSROOM = "classroom"
SCOPE_TEACHER = "openid teacher"
_SCOPES = {
    frozenset({"classroom"}): SCOPE_CLASSROOM,
    frozenset({"openid", "teacher"}): SCOPE_TEACHER,
}
SUPPORTED_SCOPES = ("classroom", "openid", "teacher")

AUTHORIZATION_CODE_TTL = timedelta(seconds=60)
ID_TOKEN_TTL = timedelta(minutes=5)
PENDING_AUTHORIZATION_TTL = timedelta(minutes=10)

# Authorization request parameters the page carries between its steps.
REQUEST_PARAMETERS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "scope",
    "state",
    "code_challenge",
    "code_challenge_method",
    "nonce",
)

_PKCE_VALUE = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
_MAX_STATE_LEN = 2048

# Redeem refusals the repository raises in English; the page shows them in Traditional Chinese.
_REDEEM_NOTICES = {
    "invalid invite": "邀請碼無效，請確認後再輸入。",
    "expired invite": "這堂課已結束，邀請碼無法再使用。",
    "classroom nickname is required": "請輸入暱稱。",
    "classroom nickname is too long": "暱稱最多 64 個字。",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class AuthorizationRequest:
    client: OAuthClientSettings
    redirect_uri: str
    scope: str
    code_challenge: str
    state: str | None = None
    nonce: str | None = None

    @property
    def is_classroom(self) -> bool:
        return self.scope == SCOPE_CLASSROOM

    @property
    def client_name(self) -> str:
        return self.client.name or self.client.client_id

    def parameters(self) -> dict[str, str]:
        params = {
            "response_type": "code",
            "client_id": self.client.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
        }
        if self.state is not None:
            params["state"] = self.state
        if self.nonce is not None:
            params["nonce"] = self.nonce
        return params


class AuthorizationRequestError(Exception):
    """An authorization request the router refuses (RFC 6749 §4.1.2.1).

    With `redirect_uri` set the client and the redirect URI were valid, so the refusal
    goes back to the client; without it the page shows the refusal itself.
    """

    def __init__(
        self,
        error: str,
        description: str,
        *,
        redirect_uri: str | None = None,
        state: str | None = None,
    ):
        super().__init__(description)
        self.error = error
        self.description = description
        self.redirect_uri = redirect_uri
        self.state = state


class TeacherOnlyError(PermissionError):
    """The `openid teacher` scope met a Google user who is neither a teacher nor an admin."""

    def __init__(self, display_name: str):
        super().__init__("teacher only")
        self.display_name = display_name


class TokenRequestError(Exception):
    """A token request the router refuses (RFC 6749 §5.2)."""

    def __init__(self, error: str, description: str, status_code: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


def redeem_notice(exc: Exception) -> str:
    message = str(exc)
    return _REDEEM_NOTICES.get(message, message)


class OAuthUseCase:
    def __init__(
        self,
        repo: RouterRepositoryPort,
        portal: PortalUseCase,
        settings: RouterSettings,
        signing_key: OAuthSigningKey,
        *,
        clock: Callable[[], datetime] = _utc_now,
        environ: Mapping[str, str] = os.environ,
    ):
        self.repo = repo
        self.portal = portal
        self.settings = settings
        self.signing_key = signing_key
        self.clock = clock
        self.environ = environ
        self.issuer = settings.public_url.rstrip("/")
        secret = settings.auth.session_secret.encode("utf-8")
        self._code_key = hmac.new(secret, b"vcr-oauth-authorization-code", hashlib.sha256).digest()
        self._pending_key = hmac.new(secret, b"vcr-oauth-pending-authorization", hashlib.sha256).digest()
        self._refresh_key = hmac.new(secret, b"vcr-oauth-classroom-refresh", hashlib.sha256).digest()

    # Discovery

    def discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/oauth/authorize",
            "token_endpoint": f"{self.issuer}/oauth/token",
            "jwks_uri": f"{self.issuer}/oauth/jwks",
            "scopes_supported": list(SUPPORTED_SCOPES),
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_post",
                "client_secret_basic",
            ],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": [self.signing_key.alg],
            "claims_supported": ["iss", "aud", "sub", "name", "iat", "exp", "nonce"],
            "authorization_response_iss_parameter_supported": True,
        }

    def jwks(self) -> dict[str, Any]:
        return self.signing_key.jwks()

    # Authorization request

    def parse_authorization_request(
        self, items: list[tuple[str, str]] | Mapping[str, str]
    ) -> AuthorizationRequest:
        pairs = list(items.items()) if isinstance(items, Mapping) else list(items)
        params: dict[str, str] = {}
        duplicated: set[str] = set()
        for name, value in pairs:
            if name not in REQUEST_PARAMETERS:
                continue
            if name in params:
                duplicated.add(name)
            params[name] = value

        client_id = params.get("client_id", "")
        client = self.settings.oauth.clients.get(client_id) if client_id else None
        if client is None or "client_id" in duplicated:
            raise AuthorizationRequestError("invalid_client", "這個應用程式沒有登記在 VCRouter。")
        redirect_uri = params.get("redirect_uri", "")
        if "redirect_uri" in duplicated or redirect_uri not in client.redirect_uris:
            raise AuthorizationRequestError("invalid_request", "這個應用程式的返回網址沒有登記在 VCRouter。")

        state = params.get("state")

        def refuse(error: str, description: str) -> AuthorizationRequestError:
            return AuthorizationRequestError(error, description, redirect_uri=redirect_uri, state=state)

        if duplicated:
            raise refuse("invalid_request", f"repeated parameter: {sorted(duplicated)[0]}")
        if state is not None and len(state) > _MAX_STATE_LEN:
            raise refuse("invalid_request", "state is too long")
        if params.get("response_type") != "code":
            raise refuse("unsupported_response_type", "response_type must be code")
        tokens = frozenset((params.get("scope") or "").split()) or frozenset(client.scopes)
        if not tokens <= frozenset(client.scopes) or tokens not in _SCOPES:
            raise refuse("invalid_scope", "scope is not allowed for this client")
        if params.get("code_challenge_method") != "S256":
            raise refuse("invalid_request", "PKCE with code_challenge_method S256 is required")
        code_challenge = params.get("code_challenge", "")
        if _PKCE_VALUE.fullmatch(code_challenge) is None:
            raise refuse("invalid_request", "code_challenge is missing or malformed")
        nonce = params.get("nonce")
        if nonce is not None and len(nonce) > 512:
            raise refuse("invalid_request", "nonce is too long")
        return AuthorizationRequest(
            client=client,
            redirect_uri=redirect_uri,
            scope=_SCOPES[tokens],
            code_challenge=code_challenge,
            state=state,
            nonce=nonce,
        )

    def error_redirect(self, error: AuthorizationRequestError) -> str:
        assert error.redirect_uri is not None
        params = {"error": error.error, "error_description": error.description}
        if error.state is not None:
            params["state"] = error.state
        params["iss"] = self.issuer
        return _with_query(error.redirect_uri, params)

    def access_denied_redirect(self, request: AuthorizationRequest) -> str:
        return self.error_redirect(
            AuthorizationRequestError(
                "access_denied",
                "the person declined or may not sign in with this scope",
                redirect_uri=request.redirect_uri,
                state=request.state,
            )
        )

    # Authorization Page outcomes

    def authorize_with_nickname(self, request: AuthorizationRequest, invite_code: str, nickname: str) -> str:
        """Nickname Redeem on the Authorization Page. A refusal raises ValueError with its notice."""
        if not request.is_classroom:
            raise ValueError("這個登入只接受 Google 帳號。")
        if not (invite_code or "").strip():
            raise ValueError("請輸入邀請碼。")
        try:
            result = self.portal.redeem_with_nickname(invite_code, nickname)
        except ValueError as exc:
            raise ValueError(redeem_notice(exc)) from None
        return self._code_redirect(request, int(self._redeemed_user_id(result)), int(result["session"]["id"]))

    def authorize_with_google_user(
        self, request: AuthorizationRequest, user_id: int, invite_code: str | None
    ) -> str:
        """The Google path: a Portal Session redeem, or a teacher sign-in."""
        if request.is_classroom:
            if not (invite_code or "").strip():
                raise ValueError("請輸入邀請碼。")
            try:
                result = self.portal.redeem(user_id, invite_code or "")
            except ValueError as exc:
                raise ValueError(redeem_notice(exc)) from None
            return self._code_redirect(request, user_id, int(result["session"]["id"]))
        user = self.repo.get_user(user_id)
        if user is None or not _may_teach(user):
            raise TeacherOnlyError(str((user or {}).get("name") or ""))
        return self._code_redirect(request, user_id, None)

    def _redeemed_user_id(self, result: dict[str, Any]) -> int:
        context = self.repo.verify_api_key_context(result["api_key"])
        if context is None or context.user_id is None:
            raise ValueError("無法領取這堂課的 API Key，請稍後再試。")
        return int(context.user_id)

    def _code_redirect(self, request: AuthorizationRequest, user_id: int, session_id: int | None) -> str:
        expires = self.clock() + AUTHORIZATION_CODE_TTL
        grant = {
            "n": secrets.token_urlsafe(18),
            "c": request.client.client_id,
            "r": request.redirect_uri,
            "p": request.code_challenge,
            "s": request.scope,
            "u": int(user_id),
            "k": session_id,
            "e": int(expires.timestamp()),
        }
        if request.nonce is not None:
            grant["o"] = request.nonce
        params = {"code": self._seal(self._code_key, grant)}
        if request.state is not None:
            params["state"] = request.state
        params["iss"] = self.issuer
        return _with_query(request.redirect_uri, params)

    # The Google round trip keeps the request, and the Invite Code, in a signed cookie.

    def seal_pending(self, request: AuthorizationRequest, invite_code: str | None) -> str:
        expires = self.clock() + PENDING_AUTHORIZATION_TTL
        return self._seal(
            self._pending_key,
            {"q": request.parameters(), "i": invite_code or "", "e": int(expires.timestamp())},
        )

    def open_pending(self, sealed: str | None) -> tuple[AuthorizationRequest, str] | None:
        payload = self._open(self._pending_key, sealed or "")
        if payload is None or not isinstance(payload.get("q"), dict):
            return None
        try:
            request = self.parse_authorization_request(
                {str(k): str(v) for k, v in payload["q"].items()}
            )
        except AuthorizationRequestError:
            return None
        return request, str(payload.get("i") or "")

    # Token endpoint

    def exchange(self, form: Mapping[str, str], authorization: str | None) -> dict[str, Any]:
        client = self._authenticate_client(form, authorization)
        grant_type = form.get("grant_type")
        if grant_type == "refresh_token":
            return self._refresh_classroom_token(client, form)
        if grant_type != "authorization_code":
            raise TokenRequestError("unsupported_grant_type", "grant_type must be authorization_code or refresh_token")
        code = form.get("code") or ""
        if not code:
            raise TokenRequestError("invalid_request", "code is required")
        verifier = form.get("code_verifier") or ""
        if not verifier:
            raise TokenRequestError("invalid_request", "code_verifier is required")
        grant = self._open(self._code_key, code)
        if grant is None or grant.get("c") != client.client_id:
            raise TokenRequestError("invalid_grant", "the code is invalid or expired")
        if not self.repo.try_consume_handoff_nonce(f"oauth-code:{grant['n']}"):
            raise TokenRequestError("invalid_grant", "the code was already used")
        if form.get("redirect_uri") != grant.get("r"):
            raise TokenRequestError("invalid_grant", "redirect_uri does not match the authorization request")
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii", "replace")).digest())
        if _PKCE_VALUE.fullmatch(verifier) is None or not hmac.compare_digest(challenge, str(grant.get("p"))):
            raise TokenRequestError("invalid_grant", "code_verifier does not match the code_challenge")
        if grant.get("s") == SCOPE_CLASSROOM:
            return self._classroom_token(client, int(grant["u"]), int(grant["k"]))
        return self._teacher_token(client, int(grant["u"]), grant.get("o"))

    def _refresh_classroom_token(self, client: OAuthClientSettings, form: Mapping[str, str]) -> dict[str, Any]:
        refresh_token = form.get("refresh_token") or ""
        if not refresh_token:
            raise TokenRequestError("invalid_request", "refresh_token is required")
        grant = self._open(self._refresh_key, refresh_token)
        if grant is None or grant.get("c") != client.client_id:
            raise TokenRequestError("invalid_grant", "the refresh token is invalid or expired")
        if SCOPE_CLASSROOM not in client.scopes:
            raise TokenRequestError("invalid_grant", "the client may no longer ask for classroom")
        return self._classroom_token(client, int(grant["u"]), int(grant["k"]))

    def _classroom_token(self, client: OAuthClientSettings, user_id: int, session_id: int) -> dict[str, Any]:
        api_key = self.repo.classroom_api_key(user_id, session_id)
        now = self.clock()
        context, _reason = self.repo.verify_api_key_with_reason(
            api_key, now=now, last_used_write_interval=timedelta(seconds=60)
        )
        if context is None or context.session_id != session_id or context.class_id is None:
            raise TokenRequestError("invalid_grant", "the student's key for this sitting is no longer usable")
        sitting = next(
            (s for s in self.repo.list_class_sessions(int(context.class_id)) if int(s["id"]) == session_id),
            None,
        )
        expires_at = parse_dt(sitting["expires_at"]) if sitting else None
        if expires_at is None:
            raise TokenRequestError("invalid_grant", "the sitting has no expiry")
        refresh_token = self._seal(
            self._refresh_key,
            {"c": client.client_id, "u": int(user_id), "k": int(session_id), "e": int(expires_at.timestamp())},
        )
        return {
            "access_token": api_key,
            "token_type": "Bearer",
            "expires_in": max(0, int((expires_at - now).total_seconds())),
            "scope": SCOPE_CLASSROOM,
            "refresh_token": refresh_token,
        }

    def _teacher_token(self, client: OAuthClientSettings, user_id: int, nonce: Any) -> dict[str, Any]:
        user = self.repo.get_user(user_id)
        if user is None or not _may_teach(user):
            raise TokenRequestError("invalid_grant", "the user may no longer sign in as a teacher")
        now = self.clock()
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": client.client_id,
            "sub": str(int(user_id)),
            "name": str(user.get("name") or ""),
            "iat": int(now.timestamp()),
            "exp": int((now + ID_TOKEN_TTL).timestamp()),
        }
        if isinstance(nonce, str):
            claims["nonce"] = nonce
        return {
            "id_token": self.signing_key.sign_jwt(claims),
            "token_type": "Bearer",
            "expires_in": int(ID_TOKEN_TTL.total_seconds()),
            "scope": SCOPE_TEACHER,
        }

    def _authenticate_client(self, form: Mapping[str, str], authorization: str | None) -> OAuthClientSettings:
        basic_id: str | None = None
        basic_secret: str | None = None
        if authorization and authorization[:6].lower() == "basic ":
            try:
                decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                raise TokenRequestError("invalid_client", "unreadable Basic credentials", 401) from None
            if ":" not in decoded:
                raise TokenRequestError("invalid_client", "unreadable Basic credentials", 401)
            raw_id, raw_secret = decoded.split(":", 1)
            basic_id, basic_secret = unquote_plus(raw_id), unquote_plus(raw_secret)
        form_id = form.get("client_id") or None
        form_secret = form.get("client_secret") or None
        if basic_id is not None and form_secret is not None:
            raise TokenRequestError("invalid_request", "use one client authentication method")
        if basic_id is not None and form_id is not None and form_id != basic_id:
            raise TokenRequestError("invalid_client", "client_id does not match the credentials", 401)
        client_id = basic_id if basic_id is not None else form_id
        client = self.settings.oauth.clients.get(client_id or "")
        if client is None:
            raise TokenRequestError("invalid_client", "unknown client", 401)
        if client.has_secret:
            presented = basic_secret if basic_id is not None else form_secret
            if not presented or not self._secret_matches(client, presented):
                raise TokenRequestError("invalid_client", "client authentication failed", 401)
        return client

    def _secret_matches(self, client: OAuthClientSettings, presented: str) -> bool:
        presented_digest = hashlib.sha256(presented.encode("utf-8")).digest()
        if client.client_secret_sha256:
            return hmac.compare_digest(presented_digest, bytes.fromhex(client.client_secret_sha256))
        stored = self.environ.get(client.client_secret_env) or ""
        if not stored:
            return False
        return hmac.compare_digest(presented_digest, hashlib.sha256(stored.encode("utf-8")).digest())

    # Signed payloads

    def _seal(self, key: bytes, payload: dict[str, Any]) -> str:
        body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        return f"{body}.{_b64url(hmac.new(key, body.encode('ascii'), hashlib.sha256).digest())}"

    def _open(self, key: bytes, sealed: str) -> dict[str, Any] | None:
        body, _, signature = sealed.partition(".")
        if not body or not signature:
            return None
        expected = _b64url(hmac.new(key, body.encode("ascii", "replace"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None
        try:
            payload = json.loads(_b64url_decode(body))
        except (ValueError, binascii.Error):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("e"), int):
            return None
        if self.clock().timestamp() >= payload["e"]:
            return None
        return payload


def _may_teach(user: dict[str, Any]) -> bool:
    roles = set(user.get("roles") or [user.get("role")])
    return user.get("status", "active") == "active" and bool(roles & {"teacher", "admin"})


def _with_query(uri: str, params: dict[str, str]) -> str:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(params.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
