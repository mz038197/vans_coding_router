from pathlib import Path
from urllib.parse import quote
import logging
from ipaddress import ip_address

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel

from src.application.use_cases.portal_use_case import PortalUseCase
from src.domain.errors import MissingTargetError, QuarantineReleaseCooldownError
from src.infrastructure.auth.client_api_key import normalize_api_key
from src.infrastructure.auth.extension_handoff import (
    build_extension_uri,
    handoff_complete_html,
)
from src.infrastructure.auth.google_oauth import GoogleOAuthService
from src.infrastructure.config import RouterSettings
from src.domain.session_model_allowlist import MODEL_ALLOWLIST_UNCHANGED
from src.infrastructure.vscode.install_vscode_models_script import (
    build_install_vscode_models_zip,
    render_install_vscode_models_cmd,
    render_install_vscode_models_command,
    render_install_vscode_models_script,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PORTAL_HTML_PATH = WEB_DIR / "portal.html"
PORTAL_CSS_PATH = WEB_DIR / "portal.css"
PORTAL_WEBMCP_PATH = WEB_DIR / "portal_webmcp.js"
PORTAL_BRAND_LOGO_PATH = WEB_DIR / "brand-logo.png"
WEBMCP_INVOCATION_CHANNEL_HEADER = "X-Vans-Invocation-Channel"
logger = logging.getLogger(__name__)


def _classroom_api_key(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return normalize_api_key(auth_header[7:]) or ""
    return normalize_api_key(request.headers.get("X-API-Key")) or ""


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _browser_description(user_agent: str) -> str:
    value = user_agent.lower()
    browser = (
        "Edge" if "edg/" in value else
        "Chrome" if "chrome/" in value else
        "Firefox" if "firefox/" in value else
        "Safari" if "safari/" in value else
        "Browser"
    )
    platform = (
        "Windows" if "windows" in value else
        "macOS" if "mac os" in value else
        "Android" if "android" in value else
        "iOS" if "iphone" in value or "ipad" in value else
        "Linux" if "linux" in value else
        "Unknown OS"
    )
    return f"{browser} on {platform}"


def _webmcp_invocation_channel(request: Request) -> str | None:
    raw = request.headers.get(WEBMCP_INVOCATION_CHANNEL_HEADER, "").strip().lower()
    if raw == "webmcp":
        return "webmcp"
    return None


class GoogleLoginRequest(BaseModel):
    email: str
    name: str
    google_sub: str | None = None
    client: str | None = None


class ExtensionRedeemRequest(BaseModel):
    handoff_token: str
    invite_code: str


class NicknameRedeemRequest(BaseModel):
    invite_code: str
    nickname: str


class ClassRequest(BaseModel):
    name: str
    ends_at: str | None = None
    api_key_ttl_hours: int | None = None


class RedeemRequest(BaseModel):
    invite_code: str


class SessionRequest(BaseModel):
    name: str
    session_at: str | None = None
    ttl_hours: int | None = None


class SessionPatchRequest(BaseModel):
    expires_at: str | None = None
    name: str | None = None
    image_generation_enabled: bool | None = None
    tts_enabled: bool | None = None
    speech_transcription_enabled: bool | None = None
    prompt_logging_enabled: bool | None = None
    status: str | None = None
    course_catalog_yaml: str | None = None
    seat_limit: int | None = None
    model_allowlist: list[str] | None = None


class UserPatchRequest(BaseModel):
    role: str | None = None
    roles: list[str] | None = None
    status: str | None = None


class MemberPatchRequest(BaseModel):
    status: str


class ClassPatchRequest(BaseModel):
    status: str


class SettingsPatchRequest(BaseModel):
    archive_after_days: int | None = None
    delete_after_days: int | None = None
    student_default_ttl_hours: int | None = None
    open_registration: bool | None = None


class PromptLogDeleteRequest(BaseModel):
    user_ids: list[int]


class QuarantineReleaseRequest(BaseModel):
    reason: str | None = None


def create_portal_router(portal_use_case: PortalUseCase, settings: RouterSettings) -> APIRouter:
    router = APIRouter(tags=["Portal"])
    oauth = GoogleOAuthService(
        client_id=settings.auth.google_client_id,
        client_secret=settings.auth.google_client_secret,
        redirect_uri=f"{settings.public_url.rstrip('/')}/auth/google/callback",
        session_secret=settings.auth.session_secret,
    )
    secure_cookie = settings.public_url.lower().startswith("https://")
    portal_session_cookie = (
        "__Host-vcr_portal_session" if secure_cookie else "vcr_portal_session"
    )

    def portal_call(fn):
        try:
            return fn()
        except HTTPException:
            raise
        except MissingTargetError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
        except PermissionError:
            raise HTTPException(status_code=403, detail="權限不足") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except OSError as exc:
            raise HTTPException(status_code=503, detail="設定檔不可寫入") from exc
        except Exception:
            logger.exception("Portal request failed")
            raise HTTPException(status_code=500, detail="伺服器錯誤，請稍後再試") from None

    def current_user_id(portal_session_token: str | None) -> int:
        if not portal_session_token:
            raise HTTPException(status_code=401, detail="尚未登入")
        context = portal_use_case.authenticate_portal_session(portal_session_token)
        if context is None:
            raise HTTPException(status_code=401, detail="尚未登入")
        return context.user_id

    def portal_session_context(request: Request):
        token = request.cookies.get(portal_session_cookie, "")
        context = portal_use_case.authenticate_portal_session(token)
        if context is None:
            raise HTTPException(status_code=401, detail="尚未登入")
        return context

    def portal_session_user_id(request: Request) -> int:
        return portal_session_context(request).user_id

    def _set_session(response: Response, user_id: int, request: Request) -> None:
        browser_description = _browser_description(request.headers.get("user-agent") or "")
        token, _ = portal_use_case.create_portal_session(user_id, browser_description)
        response.set_cookie(
            portal_session_cookie,
            token,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
            max_age=7 * 24 * 60 * 60,
            path="/",
        )
        response.delete_cookie("session_user_id", path="/")

    def _portal_redirect(error: str | None = None) -> RedirectResponse:
        target = "/portal"
        if error:
            target = f"/portal?login_error={quote(error)}"
        return RedirectResponse(url=target, status_code=302)

    async def _enforce_portal_origin(request: Request) -> None:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        path = request.url.path
        protected = (
            path == "/auth/google"
            or path == "/auth/logout"
            or path.startswith("/auth/sessions")
            or path.startswith("/portal/teacher")
            or path.startswith("/teacher/")
            or path == "/sessions/redeem"
            or path.startswith("/admin/")
        )
        if not protected:
            return
        expected = settings.public_url.rstrip("/")
        if request.headers.get("origin", "").rstrip("/") != expected:
            raise HTTPException(status_code=403, detail="不允許的請求來源")

    router.dependencies.append(Depends(_enforce_portal_origin))

    @router.get("/portal", response_class=HTMLResponse)
    async def portal_page():
        return HTMLResponse(PORTAL_HTML_PATH.read_text(encoding="utf-8"))

    @router.get("/portal/static/portal.css")
    async def portal_css():
        if not PORTAL_CSS_PATH.is_file():
            raise HTTPException(status_code=404, detail="portal.css not found")
        return Response(
            content=PORTAL_CSS_PATH.read_text(encoding="utf-8"),
            media_type="text/css",
        )

    @router.get("/portal/static/portal_webmcp.js")
    async def portal_webmcp():
        if not PORTAL_WEBMCP_PATH.is_file():
            raise HTTPException(status_code=404, detail="portal_webmcp.js not found")
        return Response(
            content=PORTAL_WEBMCP_PATH.read_text(encoding="utf-8"),
            media_type="text/javascript",
        )

    @router.get("/portal/static/brand-logo.png")
    async def portal_brand_logo():
        if not PORTAL_BRAND_LOGO_PATH.is_file():
            raise HTTPException(status_code=404, detail="brand-logo.png not found")
        return Response(
            content=PORTAL_BRAND_LOGO_PATH.read_bytes(),
            media_type="image/png",
        )

    @router.get("/auth/config")
    async def auth_config():
        return {
            "oauth_enabled": oauth.is_configured(),
            "redirect_uri": oauth.redirect_uri if oauth.is_configured() else None,
            "public_url": settings.public_url.rstrip("/"),
        }

    @router.get("/auth/google/login")
    async def google_login_start(client: str | None = Query(default=None)):
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
        if (client or "").strip().lower() == "extension":
            redirect.set_cookie(
                "oauth_client",
                "extension",
                httponly=True,
                samesite="lax",
                max_age=600,
                secure=secure_cookie,
            )
        else:
            redirect.delete_cookie("oauth_client")
        return redirect

    @router.get("/auth/google/callback")
    async def google_login_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        oauth_state: str | None = Cookie(default=None),
        oauth_client: str | None = Cookie(default=None),
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
            logger.exception("Google login callback failed")
            return _portal_redirect("Google 登入失敗，請稍後再試")

        if (oauth_client or "").strip().lower() == "extension":
            token = portal_use_case.issue_extension_handoff(int(user["id"]))
            redirect = RedirectResponse(
                url=f"/auth/extension/complete?token={quote(token)}",
                status_code=302,
            )
            redirect.delete_cookie("oauth_state")
            redirect.delete_cookie("oauth_client")
            _set_session(redirect, user["id"], request)
            return redirect

        redirect = _portal_redirect()
        redirect.delete_cookie("oauth_state")
        redirect.delete_cookie("oauth_client")
        _set_session(redirect, user["id"], request)
        return redirect

    @router.get("/auth/extension/complete", response_class=HTMLResponse)
    async def extension_handoff_complete(token: str = Query(...)):
        cleaned = (token or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="missing handoff token")
        html = handoff_complete_html(
            cleaned,
            vscode_uri=build_extension_uri(cleaned, uri_scheme="vscode"),
            cursor_uri=build_extension_uri(cleaned, uri_scheme="cursor"),
        )
        return HTMLResponse(html)

    @router.post("/auth/google")
    async def google_login_dev(data: GoogleLoginRequest, response: Response, request: Request):
        if oauth.is_configured():
            raise HTTPException(status_code=403, detail="請使用 Google OAuth 登入")
        if not settings.auth.dev_auth_enabled:
            raise HTTPException(status_code=403, detail="開發登入未啟用")
        if not _is_loopback_host(request.url.hostname):
            raise HTTPException(status_code=403, detail="開發登入僅限本機")
        user = portal_use_case.google_login(data.email, data.name, data.google_sub)
        _set_session(response, user["id"], request)
        payload: dict = {"user": user}
        if (data.client or "").strip().lower() == "extension":
            payload["handoff_token"] = portal_use_case.issue_extension_handoff(int(user["id"]))
        return payload

    @router.get("/extension/chat-language-models")
    async def extension_chat_language_models(request: Request):
        api_key = _classroom_api_key(request)
        return portal_call(
            lambda: portal_use_case.chat_language_models_template(api_key or None)
        )

    @router.post("/extension/sessions/redeem")
    async def extension_redeem(data: ExtensionRedeemRequest):
        return portal_call(
            lambda: portal_use_case.redeem_with_handoff(data.handoff_token, data.invite_code)
        )

    @router.post("/extension/sessions/nickname-redeem")
    async def extension_nickname_redeem(data: NicknameRedeemRequest):
        return portal_call(
            lambda: portal_use_case.redeem_with_nickname(data.invite_code, data.nickname)
        )

    @router.get("/extension/course-catalog")
    async def extension_course_catalog(request: Request):
        api_key = _classroom_api_key(request)
        if not api_key:
            raise HTTPException(status_code=401, detail="缺少 Classroom API Key")
        return portal_call(lambda: portal_use_case.extension_course_catalog(api_key))

    @router.get("/auth/me")
    async def me(request: Request):
        user = portal_use_case.me(portal_session_user_id(request))
        if not user:
            raise HTTPException(status_code=404, detail="找不到使用者")
        return user

    @router.post("/auth/logout")
    async def logout(request: Request, response: Response):
        token = request.cookies.get(portal_session_cookie, "")
        if token:
            portal_use_case.revoke_current_portal_session(token)
        response.delete_cookie(
            portal_session_cookie,
            path="/",
            secure=secure_cookie,
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie("session_user_id", path="/")
        return {"success": True}

    @router.get("/auth/sessions")
    async def list_portal_sessions(request: Request):
        context = portal_session_context(request)
        return {
            "items": portal_use_case.portal_sessions(
                context.user_id,
                context.session_id,
            )
        }

    @router.post("/auth/sessions/revoke-others")
    async def revoke_other_portal_sessions(request: Request):
        context = portal_session_context(request)
        revoked = portal_use_case.revoke_other_portal_sessions(
            context.user_id,
            context.session_id,
        )
        return {"revoked": revoked}

    @router.delete("/auth/sessions/{session_id}")
    async def revoke_portal_session(session_id: int, request: Request):
        context = portal_session_context(request)
        return portal_call(
            lambda: (
                portal_use_case.revoke_portal_session(context.user_id, session_id)
                or {"success": True}
            )
        )

    @router.post("/portal/teacher/api-key")
    async def teacher_key(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: portal_use_case.teacher_key(current_user_id(session_user_id)))

    @router.post("/teacher/classes")
    async def create_class(data: ClassRequest, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(
            lambda: portal_use_case.create_class(
                current_user_id(session_user_id),
                data.name.strip(),
                data.ends_at,
                data.api_key_ttl_hours,
            )
        )

    @router.get("/teacher/classes")
    async def list_my_classes(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(
            lambda: {"items": portal_use_case.list_classes(current_user_id(session_user_id))}
        )

    @router.get("/teacher/classes/{class_id}/sessions")
    async def list_sessions(class_id: int, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(
            lambda: {
                "items": portal_use_case.list_sessions(current_user_id(session_user_id), class_id),
            }
        )

    @router.get("/teacher/classes/{class_id}/sessions/{session_id}")
    async def get_session(
        class_id: int,
        session_id: int,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        session = portal_call(
            lambda: portal_use_case.get_session(
                current_user_id(session_user_id), class_id, session_id
            )
        )
        if session is None:
            raise HTTPException(status_code=404, detail="找不到課堂")
        return session

    @router.post("/teacher/classes/{class_id}/sessions")
    async def create_session(
        class_id: int,
        request: Request,
        data: SessionRequest | None = None,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        invocation_arguments = data.model_dump(exclude_none=True) if data else {}
        if "name" in invocation_arguments:
            invocation_arguments["name"] = invocation_arguments["name"].strip()
        return portal_call(
            lambda: portal_use_case.create_session(
                current_user_id(session_user_id),
                class_id,
                data.name if data else "",
                ttl_hours=data.ttl_hours if data else None,
                session_at=data.session_at if data else None,
                invocation_channel=_webmcp_invocation_channel(request),
                invocation_arguments=invocation_arguments,
            )
        )

    @router.patch("/teacher/classes/{class_id}/sessions/{session_id}")
    async def update_session(
        class_id: int,
        session_id: int,
        request: Request,
        data: SessionPatchRequest,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        invocation_arguments = data.model_dump(exclude_none=True)
        model_allowlist = (
            data.model_allowlist
            if "model_allowlist" in data.model_fields_set
            else MODEL_ALLOWLIST_UNCHANGED
        )
        if "model_allowlist" in data.model_fields_set:
            invocation_arguments["model_allowlist"] = data.model_allowlist
        session = portal_call(
            lambda: portal_use_case.update_session(
                current_user_id(session_user_id),
                class_id,
                session_id,
                expires_at=data.expires_at,
                name=data.name,
                image_generation_enabled=data.image_generation_enabled,
                tts_enabled=data.tts_enabled,
                speech_transcription_enabled=data.speech_transcription_enabled,
                prompt_logging_enabled=data.prompt_logging_enabled,
                status=data.status,
                course_catalog_yaml=data.course_catalog_yaml,
                seat_limit=data.seat_limit,
                model_allowlist=model_allowlist,
                invocation_channel=_webmcp_invocation_channel(request),
                invocation_arguments=invocation_arguments,
            )
        )
        if session is None:
            raise HTTPException(status_code=404, detail="找不到課堂")
        return session

    @router.get("/teacher/classes/{class_id}/redemptions")
    async def class_redemptions(class_id: int, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: {"items": portal_use_case.redemptions(current_user_id(session_user_id), class_id)})

    @router.patch("/teacher/classes/{class_id}/members/{user_id}")
    async def class_member_status(
        class_id: int,
        user_id: int,
        data: MemberPatchRequest,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        return portal_call(
            lambda: portal_use_case.update_class_member_status(
                current_user_id(session_user_id),
                class_id,
                user_id,
                data.status,
            )
        )

    @router.get("/teacher/classes/{class_id}/usage")
    async def class_usage(class_id: int, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: {"items": portal_use_case.class_usage(current_user_id(session_user_id), class_id)})

    @router.get("/teacher/upstream-pools")
    async def upstream_pools(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: portal_use_case.upstream_pools(current_user_id(session_user_id)))

    @router.post("/teacher/upstream-pools/{provider}/keys/{key_index}/quarantine-release")
    async def release_key_quarantine(
        provider: str,
        key_index: int,
        request: Request,
        data: QuarantineReleaseRequest | None = None,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        try:
            return await portal_use_case.release_key_quarantine(
                current_user_id(session_user_id),
                provider,
                key_index,
                invocation_channel=_webmcp_invocation_channel(request),
                reason=data.reason if data else None,
            )
        except HTTPException:
            raise
        except QuarantineReleaseCooldownError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.message,
                headers={"Retry-After": str(exc.retry_after_sec)},
            ) from None
        except PermissionError:
            raise HTTPException(status_code=403, detail="權限不足") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception:
            logger.exception("Portal quarantine release failed")
            raise HTTPException(status_code=500, detail="伺服器錯誤，請稍後再試") from None

    @router.get("/teacher/classes/{class_id}/prompt-logs")
    async def prompt_logs(
        class_id: int,
        session_id: int | None = None,
        keyword: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
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
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
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
    async def redeem(data: RedeemRequest, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: portal_use_case.redeem(current_user_id(session_user_id), data.invite_code))

    @router.get("/portal/download/install-vscode-models.ps1")
    async def download_install_vscode_models(
        request: Request,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        current_user_id(session_user_id)
        template = portal_call(
            lambda: portal_use_case.chat_language_models_template(
                _classroom_api_key(request) or None
            )
        )
        script = render_install_vscode_models_script(template)
        return PlainTextResponse(
            script,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="install-vscode-models.ps1"'},
        )

    @router.get("/portal/download/install-vscode-models.cmd")
    async def download_install_vscode_models_cmd(
        request: Request,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        current_user_id(session_user_id)
        template = portal_call(
            lambda: portal_use_case.chat_language_models_template(
                _classroom_api_key(request) or None
            )
        )
        script = render_install_vscode_models_cmd(template)
        return PlainTextResponse(
            script,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="install-vscode-models.cmd"'},
        )

    @router.get("/portal/download/install-vscode-models.command")
    async def download_install_vscode_models_command(
        request: Request,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        current_user_id(session_user_id)
        template = portal_call(
            lambda: portal_use_case.chat_language_models_template(
                _classroom_api_key(request) or None
            )
        )
        script = render_install_vscode_models_command(template)
        return PlainTextResponse(
            script,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="install-vscode-models.command"'},
        )

    @router.get("/portal/download/install-vscode-models.zip")
    async def download_install_vscode_models_zip(
        request: Request,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        current_user_id(session_user_id)
        template = portal_call(
            lambda: portal_use_case.chat_language_models_template(
                _classroom_api_key(request) or None
            )
        )
        payload = build_install_vscode_models_zip(template)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="install-vscode-models.zip"'},
        )

    @router.get("/admin/users")
    async def admin_users(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: {"items": portal_use_case.admin_users(current_user_id(session_user_id))})

    @router.patch("/admin/users/{user_id}")
    async def admin_update_user(user_id: int, data: UserPatchRequest, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
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
    async def admin_classes(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: {"items": portal_use_case.admin_classes(current_user_id(session_user_id))})

    @router.patch("/admin/classes/{class_id}")
    async def admin_update_class(class_id: int, data: ClassPatchRequest, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: portal_use_case.admin_update_class(current_user_id(session_user_id), class_id, data.status))

    @router.get("/admin/settings")
    async def admin_settings(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: portal_use_case.admin_settings(current_user_id(session_user_id)))

    @router.patch("/admin/settings")
    async def admin_update_settings(data: SettingsPatchRequest, session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(
            lambda: portal_use_case.admin_update_settings(
                current_user_id(session_user_id),
                archive_after_days=data.archive_after_days,
                delete_after_days=data.delete_after_days,
                student_default_ttl_hours=data.student_default_ttl_hours,
                open_registration=data.open_registration,
            )
        )

    @router.post("/admin/archive/run")
    async def admin_archive_run(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: portal_use_case.admin_run_archive(current_user_id(session_user_id)))

    @router.post("/admin/archive/clear")
    async def admin_archive_clear(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(lambda: portal_use_case.admin_clear_archive(current_user_id(session_user_id)))

    @router.get("/admin/prompt-logs/usage")
    async def admin_prompt_log_usage(session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie)):
        return portal_call(
            lambda: {"items": portal_use_case.admin_prompt_log_usage(current_user_id(session_user_id))}
        )

    @router.post("/admin/prompt-logs/delete")
    async def admin_delete_prompt_logs(
        data: PromptLogDeleteRequest,
        session_user_id: str | None = Cookie(default=None, alias=portal_session_cookie),
    ):
        return portal_call(
            lambda: portal_use_case.admin_delete_user_prompt_logs(
                current_user_id(session_user_id),
                data.user_ids,
            )
        )

    return router
