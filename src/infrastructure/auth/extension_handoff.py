"""Short-lived Sign-in Handoff tokens for the classroom extension."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable


DEFAULT_HANDOFF_MAX_AGE_SECONDS = 600


class ExtensionHandoffService:
    """Create and consume one-shot handoff tokens (not long-lived Portal sessions)."""

    def __init__(
        self,
        *,
        session_secret: str,
        max_age_seconds: int = DEFAULT_HANDOFF_MAX_AGE_SECONDS,
        try_mark_nonce_used: Callable[[str], bool] | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.session_secret = session_secret
        self.max_age_seconds = max_age_seconds
        self._try_mark_nonce_used = try_mark_nonce_used
        self._now = now or time.time

    def create_token(self, user_id: int) -> str:
        nonce = secrets.token_urlsafe(24)
        ts = str(int(self._now()))
        payload = f"{nonce}:{int(user_id)}:{ts}"
        sig = self._sign(payload)
        return f"{payload}:{sig}"

    def consume_token(self, token: str) -> int:
        nonce, user_id, _ts = self._parse_valid(token)
        if self._try_mark_nonce_used is not None and not self._try_mark_nonce_used(nonce):
            raise ValueError("handoff already used")
        return user_id

    def _parse_valid(self, token: str) -> tuple[str, int, int]:
        parts = (token or "").strip().split(":")
        if len(parts) != 4:
            raise ValueError("invalid handoff")
        nonce, user_text, ts_text, sig = parts
        if not nonce or not user_text or not ts_text or not sig:
            raise ValueError("invalid handoff")
        try:
            user_id = int(user_text)
            ts = int(ts_text)
        except ValueError as exc:
            raise ValueError("invalid handoff") from exc
        payload = f"{nonce}:{user_id}:{ts}"
        if not hmac.compare_digest(self._sign(payload), sig):
            raise ValueError("invalid handoff")
        if self._now() - ts > self.max_age_seconds:
            raise ValueError("handoff expired")
        return nonce, user_id, ts

    def _sign(self, payload: str) -> str:
        return hmac.new(
            self.session_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


def build_extension_uri(token: str, *, uri_scheme: str = "vscode") -> str:
    """Deep-link target for the classroom extension UriHandler."""
    from urllib.parse import quote

    safe = quote(token, safe="")
    return f"{uri_scheme}://vans-coding.vans-classroom-install/handoff?token={safe}"


def handoff_complete_html(
    token: str,
    *,
    vscode_uri: str,
    cursor_uri: str,
) -> str:
    """Browser page: try deep link; show paste code fallback (never includes API key)."""
    # Escape for HTML text / attribute contexts
    def esc(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    token_esc = esc(token)
    vscode_esc = esc(vscode_uri)
    cursor_esc = esc(cursor_uri)
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>回到編輯器</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    code {{ word-break: break-all; background: #f4f4f5; padding: 0.2rem 0.35rem; border-radius: 4px; }}
    .actions a {{ display: inline-block; margin: 0.35rem 0.5rem 0.35rem 0; }}
    .hint {{ color: #52525b; font-size: 0.95rem; }}
  </style>
</head>
<body>
  <h1>Google 登入成功</h1>
  <p>正在嘗試開啟編輯器。若沒有自動開啟，請點下方連結，或複製一次性貼碼到「凡思課堂安裝」的 Router Lane。</p>
  <p class="actions">
    <a href="{vscode_esc}">開啟 VS Code</a>
    <a href="{cursor_esc}">開啟 Cursor</a>
  </p>
  <p class="hint">一次性貼碼（不是 API Key）：</p>
  <p><code id="code">{token_esc}</code></p>
  <script>
    try {{ window.location.href = {vscode_uri!r}; }} catch (e) {{}}
  </script>
</body>
</html>
"""
