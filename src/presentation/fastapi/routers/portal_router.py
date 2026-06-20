from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Cookie, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.auth.google_oauth import GoogleOAuthService
from src.infrastructure.config import RouterSettings

PORTAL_HTML_PATH = Path(__file__).resolve().parent.parent / "web" / "portal.html"


class GoogleLoginRequest(BaseModel):
    email: str
    name: str
    google_sub: str | None = None


class ClassRequest(BaseModel):
    name: str
    ends_at: str | None = None
    api_key_ttl_hours: int | None = None


class RedeemRequest(BaseModel):
    invite_code: str


class SessionRequest(BaseModel):
    session_at: str | None = None
    ttl_hours: int | None = None


class SessionPatchRequest(BaseModel):
    expires_at: str


class UserPatchRequest(BaseModel):
    role: str | None = None
    roles: list[str] | None = None
    status: str | None = None


class ClassPatchRequest(BaseModel):
    status: str


class SettingsPatchRequest(BaseModel):
    retention_days: int | None = None
    student_default_ttl_hours: int | None = None
    open_registration: bool | None = None


def create_portal_router(portal_use_case: PortalUseCase, settings: RouterSettings) -> APIRouter:
    router = APIRouter(tags=["Portal"])
    oauth = GoogleOAuthService(
        client_id=settings.auth.google_client_id,
        client_secret=settings.auth.google_client_secret,
        redirect_uri=f"{settings.public_url.rstrip('/')}/auth/google/callback",
        session_secret=settings.auth.session_secret,
    )
    secure_cookie = settings.public_url.lower().startswith("https://")

    def portal_call(fn):
        try:
            return fn()
        except PermissionError:
            raise HTTPException(status_code=403, detail="權限不足") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def current_user_id(session_user_id: str | None) -> int:
        if not session_user_id:
            raise HTTPException(status_code=401, detail="尚未登入")
        return int(session_user_id)

    def _set_session(response: Response, user_id: int) -> None:
        response.set_cookie(
            "session_user_id",
            str(user_id),
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
        )

    def _portal_redirect(error: str | None = None) -> RedirectResponse:
        target = "/portal"
        if error:
            target = f"/portal?login_error={quote(error)}"
        return RedirectResponse(url=target, status_code=302)

    @router.get("/portal", response_class=HTMLResponse)
    async def portal_page():
        return HTMLResponse(PORTAL_HTML_PATH.read_text(encoding="utf-8"))

    @router.get("/auth/config")
    async def auth_config():
        return {
            "oauth_enabled": oauth.is_configured(),
            "redirect_uri": oauth.redirect_uri if oauth.is_configured() else None,
            "public_url": settings.public_url.rstrip("/"),
        }

    @router.get("/auth/google/login")
    async def google_login_start():
        if not oauth.is_configured():
            raise HTTPException(status_code=503, detail="Google OAuth 尚未設定")
        state = oauth.create_state()
        redirect = RedirectResponse(url=oauth.authorize_url(state), status_code=302)
        redirect.set_cookie(
            "oauth_state",
            state,
            httponly=True,
            samesite="lax",
            max_age=600,
            secure=secure_cookie,
        )
        return redirect

    @router.get("/auth/google/callback")
    async def google_login_callback(
        response: Response,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        oauth_state: str | None = Cookie(default=None),
    ):
        if error:
            return _portal_redirect("Google 登入已取消")
        if not code or not state or not oauth_state:
            return _portal_redirect("Google 登入參數不完整")
        if state != oauth_state or not oauth.verify_state(state):
            return _portal_redirect("Google 登入狀態驗證失敗")
        try:
            claims = await oauth.exchange_code(code)
            user = portal_use_case.google_login(claims.email, claims.name, claims.google_sub)
        except ValueError as exc:
            return _portal_redirect(str(exc))
        except Exception:
            return _portal_redirect("Google 登入失敗，請稍後再試")

        redirect = _portal_redirect()
        redirect.delete_cookie("oauth_state")
        _set_session(redirect, user["id"])
        return redirect

    @router.post("/auth/google")
    async def google_login_dev(data: GoogleLoginRequest, response: Response):
        if oauth.is_configured():
            raise HTTPException(status_code=403, detail="請使用 Google OAuth 登入")
        user = portal_use_case.google_login(data.email, data.name, data.google_sub)
        _set_session(response, user["id"])
        return {"user": user}

    @router.get("/auth/me")
    async def me(session_user_id: str | None = Cookie(default=None)):
        user = portal_use_case.me(current_user_id(session_user_id))
        if not user:
            raise HTTPException(status_code=404, detail="找不到使用者")
        return user

    @router.post("/auth/logout")
    async def logout(response: Response):
        response.delete_cookie("session_user_id")
        return {"success": True}

    @router.post("/portal/teacher/api-key")
    async def teacher_key(session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: portal_use_case.teacher_key(current_user_id(session_user_id)))

    @router.post("/teacher/classes")
    async def create_class(data: ClassRequest, session_user_id: str | None = Cookie(default=None)):
        return portal_call(
            lambda: portal_use_case.create_class(
                current_user_id(session_user_id),
                data.name.strip(),
                data.ends_at,
                data.api_key_ttl_hours,
            )
        )

    @router.get("/teacher/classes")
    async def list_my_classes(session_user_id: str | None = Cookie(default=None)):
        user = portal_use_case.me(current_user_id(session_user_id))
        return {"items": user.get("classes", []) if user else []}

    @router.get("/teacher/classes/{class_id}/sessions")
    async def list_sessions(class_id: int, session_user_id: str | None = Cookie(default=None)):
        return portal_call(
            lambda: {
                "items": portal_use_case.list_sessions(current_user_id(session_user_id), class_id),
            }
        )

    @router.post("/teacher/classes/{class_id}/sessions")
    async def create_session(
        class_id: int,
        data: SessionRequest | None = None,
        session_user_id: str | None = Cookie(default=None),
    ):
        return portal_call(
            lambda: portal_use_case.create_session(
                current_user_id(session_user_id),
                class_id,
                ttl_hours=data.ttl_hours if data else None,
                session_at=data.session_at if data else None,
            )
        )

    @router.patch("/teacher/classes/{class_id}/sessions/{session_id}")
    async def update_session(
        class_id: int,
        session_id: int,
        data: SessionPatchRequest,
        session_user_id: str | None = Cookie(default=None),
    ):
        return portal_call(
            lambda: portal_use_case.update_session(
                current_user_id(session_user_id),
                class_id,
                session_id,
                data.expires_at,
            )
        )

    @router.get("/teacher/classes/{class_id}/redemptions")
    async def class_redemptions(class_id: int, session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: {"items": portal_use_case.redemptions(current_user_id(session_user_id), class_id)})

    @router.get("/teacher/classes/{class_id}/usage")
    async def class_usage(class_id: int, session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: {"items": portal_use_case.class_usage(current_user_id(session_user_id), class_id)})

    @router.get("/teacher/classes/{class_id}/prompt-logs")
    async def prompt_logs(
        class_id: int,
        session_id: int | None = None,
        keyword: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        session_user_id: str | None = Cookie(default=None),
    ):
        return portal_call(
            lambda: portal_use_case.prompt_logs(
                current_user_id(session_user_id),
                class_id,
                session_id,
                keyword,
                start_at,
                end_at,
            )
        )

    @router.get("/teacher/classes/{class_id}/prompt-logs/{log_id}")
    async def prompt_log_detail(
        class_id: int,
        log_id: int,
        session_user_id: str | None = Cookie(default=None),
    ):
        detail = portal_call(
            lambda: portal_use_case.prompt_log_detail(
                current_user_id(session_user_id),
                class_id,
                log_id,
            )
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="prompt log not found")
        return detail

    @router.post("/sessions/redeem")
    async def redeem(data: RedeemRequest, session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: portal_use_case.redeem(current_user_id(session_user_id), data.invite_code))

    @router.get("/admin/users")
    async def admin_users(session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: {"items": portal_use_case.admin_users(current_user_id(session_user_id))})

    @router.patch("/admin/users/{user_id}")
    async def admin_update_user(user_id: int, data: UserPatchRequest, session_user_id: str | None = Cookie(default=None)):
        return portal_call(
            lambda: portal_use_case.admin_update_user(
                current_user_id(session_user_id),
                user_id,
                data.role,
                data.status,
                data.roles,
            )
        )

    @router.get("/admin/classes")
    async def admin_classes(session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: {"items": portal_use_case.admin_classes(current_user_id(session_user_id))})

    @router.patch("/admin/classes/{class_id}")
    async def admin_update_class(class_id: int, data: ClassPatchRequest, session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: portal_use_case.admin_update_class(current_user_id(session_user_id), class_id, data.status))

    @router.get("/admin/settings")
    async def admin_settings(session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: portal_use_case.admin_settings(current_user_id(session_user_id)))

    @router.patch("/admin/settings")
    async def admin_update_settings(data: SettingsPatchRequest, session_user_id: str | None = Cookie(default=None)):
        return portal_call(
            lambda: portal_use_case.admin_update_settings(
                current_user_id(session_user_id),
                retention_days=data.retention_days,
                student_default_ttl_hours=data.student_default_ttl_hours,
                open_registration=data.open_registration,
            )
        )

    @router.post("/admin/archive/run")
    async def admin_archive_run(session_user_id: str | None = Cookie(default=None)):
        return portal_call(lambda: portal_use_case.admin_run_archive(current_user_id(session_user_id)))

    return router
