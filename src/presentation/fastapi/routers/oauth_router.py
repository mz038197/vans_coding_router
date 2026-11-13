"""OAuth authorization server endpoints and the Authorization Page (ADR 0094)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from src.application.use_cases.oauth_use_case import (
    AuthorizationRequest,
    AuthorizationRequestError,
    OAuthUseCase,
    PENDING_AUTHORIZATION_TTL,
    TeacherOnlyError,
    TokenRequestError,
)
from src.infrastructure.config import RouterSettings
from src.presentation.fastapi import oauth_pages
from src.presentation.fastapi.routers.portal_router import portal_session_cookie_name

logger = logging.getLogger(__name__)

PENDING_COOKIE = "vcr_oauth_pending"
GOOGLE_LOGIN_FOR_AUTHORIZE = "/auth/google/login?client=authorize"
RESUME_PATH = "/oauth/authorize/resume"

_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'; form-action 'self'",
    "Referrer-Policy": "same-origin",
}
_TOKEN_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _html(content: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(content, status_code=status_code, headers=_PAGE_HEADERS)


def _redirect(url: str, status_code: int = 302) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=status_code, headers=_PAGE_HEADERS)


def create_oauth_router(oauth: OAuthUseCase, settings: RouterSettings) -> APIRouter:
    router = APIRouter(tags=["OAuth"])
    public_url = settings.public_url.rstrip("/")
    secure_cookie = public_url.lower().startswith("https://")
    portal_cookie = portal_session_cookie_name(settings.public_url)
    google_configured = bool(settings.auth.google_client_id and settings.auth.google_client_secret)

    def refused(error: AuthorizationRequestError) -> Response:
        if error.redirect_uri is None:
            return _html(oauth_pages.refusal_page(error.description), status_code=400)
        return _redirect(oauth.error_redirect(error))

    def page(request: AuthorizationRequest, *, error: str | None = None, status_code: int = 200, **fields) -> HTMLResponse:
        if request.is_classroom:
            return _html(oauth_pages.classroom_page(request, error=error, **fields), status_code=status_code)
        return _html(oauth_pages.teacher_page(request, error=error), status_code=status_code)

    def portal_user_id(http_request: Request) -> int | None:
        token = http_request.cookies.get(portal_cookie, "")
        if not token:
            return None
        context = oauth.portal.authenticate_portal_session(token)
        return context.user_id if context is not None else None

    def google_outcome(request: AuthorizationRequest, user_id: int, invite_code: str) -> Response:
        try:
            url = oauth.authorize_with_google_user(request, user_id, invite_code)
        except TeacherOnlyError as exc:
            response = _html(
                oauth_pages.teacher_only_page(request, exc.display_name, oauth.access_denied_redirect(request)),
                status_code=403,
            )
            response.delete_cookie(PENDING_COOKIE, path="/oauth")
            return response
        except ValueError as exc:
            return page(request, error=str(exc), status_code=400, invite_code=invite_code)
        response = _redirect(url)
        response.delete_cookie(PENDING_COOKIE, path="/oauth")
        return response

    @router.get("/.well-known/oauth-authorization-server")
    @router.get("/.well-known/openid-configuration")
    async def discovery():
        return JSONResponse(oauth.discovery(), headers={"Access-Control-Allow-Origin": "*"})

    @router.get("/oauth/jwks")
    async def jwks():
        return JSONResponse(oauth.jwks(), headers={"Access-Control-Allow-Origin": "*"})

    @router.get("/oauth/authorize", response_class=HTMLResponse)
    async def authorize_page(http_request: Request):
        try:
            request = oauth.parse_authorization_request(http_request.query_params.multi_items())
        except AuthorizationRequestError as exc:
            return refused(exc)
        return page(request)

    @router.post("/oauth/authorize", response_class=HTMLResponse)
    async def authorize_submit(http_request: Request):
        if http_request.headers.get("origin", "").rstrip("/") != public_url:
            return _html(oauth_pages.refusal_page("不允許的請求來源。"), status_code=403)
        form = await http_request.form()
        try:
            request = oauth.parse_authorization_request(
                [(k, v) for k, v in form.multi_items() if isinstance(v, str)]
            )
        except AuthorizationRequestError as exc:
            return refused(exc)
        method = str(form.get("method") or "")
        invite_code = str(form.get("invite_code") or "").strip()
        nickname = str(form.get("nickname") or "")

        if method == "nickname":
            try:
                url = oauth.authorize_with_nickname(request, invite_code, nickname)
            except ValueError as exc:
                return page(request, error=str(exc), status_code=400, invite_code=invite_code, nickname=nickname)
            return _redirect(url, status_code=303)

        if method != "google":
            return page(request, error="請選擇加入方式。", status_code=400, invite_code=invite_code, nickname=nickname)
        if request.is_classroom and not invite_code:
            return page(request, error="請先輸入邀請碼，再改用 Google 帳號加入。", status_code=400, nickname=nickname)
        if google_configured:
            target = GOOGLE_LOGIN_FOR_AUTHORIZE
        elif settings.auth.dev_auth_enabled:
            # Local development: the Portal's development login stands in for Google.
            target = RESUME_PATH
        else:
            return page(request, error="Google 登入尚未設定。", status_code=503, invite_code=invite_code)
        response = _redirect(target, status_code=303)
        response.set_cookie(
            PENDING_COOKIE,
            oauth.seal_pending(request, invite_code if request.is_classroom else None),
            max_age=int(PENDING_AUTHORIZATION_TTL.total_seconds()),
            path="/oauth",
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
        )
        return response

    @router.get(RESUME_PATH, response_class=HTMLResponse)
    async def authorize_resume(http_request: Request, login_error: str | None = None):
        pending = oauth.open_pending(http_request.cookies.get(PENDING_COOKIE))
        if pending is None:
            return _html(
                oauth_pages.refusal_page("這次授權已逾時或無效，請回到原本的應用程式重新開始。"),
                status_code=400,
            )
        request, invite_code = pending
        if login_error:
            return page(request, error=login_error, status_code=400, invite_code=invite_code)
        user_id = portal_user_id(http_request)
        if user_id is None:
            return page(request, error="Google 登入沒有完成，請再試一次。", status_code=401, invite_code=invite_code)
        return google_outcome(request, user_id, invite_code)

    @router.post("/oauth/token")
    async def token(http_request: Request):
        form = await http_request.form()
        fields: dict[str, str] = {}
        for name, value in form.multi_items():
            if not isinstance(value, str):
                continue
            if name in fields:
                return _token_error(TokenRequestError("invalid_request", f"repeated parameter: {name}"))
            fields[name] = value
        try:
            answer = oauth.exchange(fields, http_request.headers.get("authorization"))
        except TokenRequestError as exc:
            return _token_error(exc)
        return JSONResponse(answer, headers=_TOKEN_HEADERS)

    return router


def _token_error(exc: TokenRequestError) -> JSONResponse:
    headers = dict(_TOKEN_HEADERS)
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = 'Basic realm="oauth"'
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status_code,
        headers=headers,
    )
