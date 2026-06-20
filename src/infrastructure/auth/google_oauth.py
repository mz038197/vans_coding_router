from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_MAX_AGE_SECONDS = 600


@dataclass(frozen=True)
class GoogleUserClaims:
    email: str
    name: str
    google_sub: str


class GoogleOAuthService:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        session_secret: str,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.redirect_uri = redirect_uri
        self.session_secret = session_secret

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def create_state(self) -> str:
        nonce = secrets.token_urlsafe(32)
        ts = str(int(time.time()))
        payload = f"{nonce}:{ts}"
        sig = hmac.new(
            self.session_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{payload}:{sig}"

    def verify_state(self, state: str) -> bool:
        parts = state.split(":")
        if len(parts) != 3:
            return False
        nonce, ts_text, sig = parts
        if not nonce or not ts_text or not sig:
            return False
        try:
            ts = int(ts_text)
        except ValueError:
            return False
        if time.time() - ts > STATE_MAX_AGE_SECONDS:
            return False
        payload = f"{nonce}:{ts_text}"
        expected = hmac.new(
            self.session_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, sig)

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> GoogleUserClaims:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": self.redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                response.raise_for_status()
                token_payload = response.json()
        except httpx.HTTPStatusError as exc:
            try:
                payload = exc.response.json()
                detail = payload.get("error_description") or payload.get("error") or exc.response.text
            except ValueError:
                detail = exc.response.text
            raise ValueError(f"Google token 交換失敗: {detail}") from exc
        except httpx.TimeoutException as exc:
            raise ValueError(
                "無法連線 Google OAuth 服務（連線逾時）。請確認伺服器可對外連線 oauth2.googleapis.com:443"
            ) from exc
        except httpx.HTTPError as exc:
            raise ValueError(f"無法連線 Google OAuth 服務: {exc}") from exc

        id_token_jwt = token_payload.get("id_token")
        if not id_token_jwt:
            raise ValueError("Google 未回傳 id_token")

        try:
            claims = id_token.verify_oauth2_token(
                id_token_jwt,
                google_requests.Request(),
                self.client_id,
            )
        except Exception as exc:
            raise ValueError(f"Google id_token 驗證失敗: {exc}") from exc
        if not claims.get("email_verified"):
            raise ValueError("Google 帳號尚未驗證 email")

        email = str(claims.get("email", "")).strip().lower()
        if not email:
            raise ValueError("Google 未提供 email")

        return GoogleUserClaims(
            email=email,
            name=str(claims.get("name") or email.split("@", 1)[0]),
            google_sub=str(claims["sub"]),
        )
