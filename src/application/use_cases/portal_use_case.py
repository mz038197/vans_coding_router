from datetime import UTC, datetime
import time
from typing import Any

from src.domain.entities.agent_action_audit import AgentActionAudit
from src.domain.entities.auth import PortalSessionContext
from src.domain.errors import MissingTargetError, QuarantineReleaseCooldownError
from src.domain.ports.router_repository import RouterRepositoryPort
from src.infrastructure.auth.extension_handoff import ExtensionHandoffService
from src.infrastructure.config import RouterSettings, apply_runtime_settings, settings_summary
from src.infrastructure.repositories.router_repository_helpers import parse_dt
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template

_VALID_ROLES = frozenset({"admin", "teacher", "student"})
_VALID_STATUSES = frozenset({"active", "inactive"})
_VALID_SESSION_STATUSES = frozenset({"active", "ended"})
_NICKNAME_MAX_LEN = 64
_WEBMCP_QUARANTINE_RELEASE_COOLDOWN_SEC = 60.0
_WEBMCP_QUARANTINE_RELEASE_DEFAULT_REASON = (
    "Teacher explicitly requested Quarantine Release through WebMCP"
)
_SESSION_CAPABILITY_FIELDS = frozenset(
    {
        "image_generation_enabled",
        "tts_enabled",
        "speech_transcription_enabled",
        "prompt_logging_enabled",
    }
)


class PortalUseCase:
    def __init__(
        self,
        repo: RouterRepositoryPort,
        base_settings: RouterSettings,
        llm_gateway: Any | None = None,
    ):
        self.repo = repo
        self._base_settings = base_settings
        self._llm_gateway = llm_gateway
        self._agent_quarantine_release_at: dict[tuple[str, int], float] = {}
        self.refresh_settings()

    def refresh_settings(self) -> None:
        self.settings = apply_runtime_settings(self._base_settings, self.repo.get_runtime_settings())
        self.repo.settings = self.settings

    def google_login(self, email: str, name: str, google_sub: str | None = None) -> dict[str, Any]:
        existing = self.repo.get_user_by_email(email)
        if not existing and not self.settings.auth.open_registration:
            raise ValueError("尚未開放註冊")
        return self.repo.upsert_google_user(email=email, name=name, google_sub=google_sub)

    def authenticate_portal_session(
        self,
        token: str,
        *,
        refresh_activity: bool = True,
    ) -> PortalSessionContext | None:
        return self.repo.authenticate_portal_session(
            token,
            refresh_activity=refresh_activity,
        )

    def create_portal_session(
        self,
        user_id: int,
        browser_description: str,
    ) -> tuple[str, PortalSessionContext]:
        return self.repo.create_portal_session(user_id, browser_description)

    def revoke_current_portal_session(self, token: str) -> bool:
        context = self.repo.authenticate_portal_session(token)
        if context is None:
            return False
        return self.repo.revoke_portal_session(
            context.user_id,
            context.session_id,
            "user_logout",
        )

    def portal_sessions(
        self,
        user_id: int,
        current_session_id: int,
    ) -> list[dict[str, Any]]:
        sessions = self.repo.list_portal_sessions(user_id)
        return [
            {**session, "current": int(session["id"]) == current_session_id}
            for session in sessions
        ]

    def revoke_portal_session(self, user_id: int, session_id: int) -> None:
        if not self.repo.revoke_portal_session(
            user_id,
            session_id,
            "user_device_revoke",
        ):
            raise ValueError("找不到登入裝置")

    def revoke_other_portal_sessions(self, user_id: int, current_session_id: int) -> int:
        return self.repo.revoke_other_portal_sessions(
            user_id,
            current_session_id,
            "user_revoke_others",
        )

    def me(self, user_id: int) -> dict[str, Any] | None:
        user = self.repo.get_user(user_id)
        if not user:
            return None
        user["keys"] = self.repo.get_active_keys(user_id)
        if self._has_role(user, "teacher") or self._has_role(user, "admin"):
            user["classes"] = self.repo.list_classes(teacher_id=user_id)
        return user

    def teacher_key(self, user_id: int) -> dict[str, str]:
        user = self.repo.get_user(user_id)
        if not user or not (self._has_role(user, "teacher") or self._has_role(user, "admin")):
            raise PermissionError("teacher only")
        return {"api_key": self.repo.issue_long_lived_key(user_id)}

    def upstream_pools(self, user_id: int) -> dict[str, Any]:
        self._assert_teacher(user_id)
        gateway = self._llm_gateway
        if gateway is None:
            return {"providers": {}}
        status_fn = getattr(gateway, "pool_status", None)
        if not callable(status_fn):
            return {"providers": {}}
        return status_fn(limited_only=True)

    async def release_key_quarantine(
        self,
        user_id: int,
        provider: str,
        index: int,
        *,
        invocation_channel: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        self._assert_teacher(user_id)
        if not isinstance(provider, str):
            raise ValueError("provider 不可為空")
        provider = provider.strip()
        if not provider:
            raise ValueError("provider 不可為空")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("key index 必須為非負整數")
        gateway = self._llm_gateway
        if gateway is None:
            raise ValueError("上游 gateway 未設定")
        release_fn = getattr(gateway, "release_key_quarantine", None)
        if not callable(release_fn):
            raise ValueError("此 gateway 不支援解除隔離")
        is_agent_action = invocation_channel == "webmcp"
        reservation_time: float | None = None
        if is_agent_action:
            reservation_time = self._reserve_agent_quarantine_release(provider, index)
            try:
                self._assert_key_quarantined(gateway, provider, index)
            except Exception:
                self._forget_agent_quarantine_release(provider, index, reservation_time)
                raise
        try:
            await release_fn(provider, index)
        except (KeyError, IndexError) as exc:
            if reservation_time is not None:
                self._forget_agent_quarantine_release(provider, index, reservation_time)
            raise ValueError(str(exc)) from exc
        except BaseException:
            if reservation_time is not None:
                self._forget_agent_quarantine_release(provider, index, reservation_time)
            raise
        if is_agent_action:
            audit_reason = self._quarantine_release_reason(reason)
            self._agent_quarantine_release_at[(provider, index)] = time.monotonic()
            self.repo.record_agent_action_audit(
                actor_user_id=user_id,
                action="release_key_quarantine",
                class_id=None,
                session_id=None,
                arguments={
                    "key_index": index,
                    "provider": provider,
                    "reason": audit_reason,
                },
                invocation_channel="webmcp",
            )
        return {"ok": True, "provider": provider, "index": index}

    @staticmethod
    def _quarantine_release_reason(reason: str | None) -> str:
        if isinstance(reason, str) and reason.strip():
            return reason.strip()[:500]
        return _WEBMCP_QUARANTINE_RELEASE_DEFAULT_REASON

    def _reserve_agent_quarantine_release(self, provider: str, index: int) -> float:
        now = time.monotonic()
        key = (provider, index)
        previous = self._agent_quarantine_release_at.get(key)
        if previous is not None:
            remaining = _WEBMCP_QUARANTINE_RELEASE_COOLDOWN_SEC - (now - previous)
            if remaining > 0:
                raise QuarantineReleaseCooldownError(remaining)
        else:
            persisted = self._persisted_agent_quarantine_release(provider, index)
            if persisted is not None:
                elapsed = (datetime.now(UTC) - persisted).total_seconds()
                remaining = _WEBMCP_QUARANTINE_RELEASE_COOLDOWN_SEC - elapsed
                if remaining > 0:
                    raise QuarantineReleaseCooldownError(remaining)
        self._agent_quarantine_release_at[key] = now
        return now

    def _persisted_agent_quarantine_release(
        self,
        provider: str,
        index: int,
    ) -> datetime | None:
        for audit in self.repo.list_agent_action_audits(
            action="release_key_quarantine",
            invocation_channel="webmcp",
            limit=None,
        ):
            arguments = audit.get("arguments")
            if not isinstance(arguments, dict) or arguments.get("provider") != provider:
                continue
            try:
                audit_index = int(arguments.get("key_index"))
            except (TypeError, ValueError):
                continue
            if audit_index != index:
                continue
            occurred_at = audit.get("occurred_at")
            if occurred_at is None:
                continue
            try:
                return parse_dt(str(occurred_at))
            except ValueError:
                continue
        return None

    def _forget_agent_quarantine_release(
        self,
        provider: str,
        index: int,
        reservation_time: float,
    ) -> None:
        key = (provider, index)
        if self._agent_quarantine_release_at.get(key) == reservation_time:
            self._agent_quarantine_release_at.pop(key, None)

    @staticmethod
    def _assert_key_quarantined(gateway: Any, provider: str, index: int) -> None:
        state_fn = getattr(gateway, "is_key_quarantined", None)
        if callable(state_fn):
            try:
                quarantined = state_fn(provider, index)
            except (KeyError, IndexError) as exc:
                raise ValueError(str(exc)) from exc
            if not quarantined:
                raise ValueError("指定的上游金鑰目前不在隔離中")
            return

        status_fn = getattr(gateway, "pool_status", None)
        if not callable(status_fn):
            raise ValueError("無法確認指定的上游金鑰是否在隔離中")
        status = status_fn(limited_only=False)
        providers = status.get("providers") if isinstance(status, dict) else None
        provider_status = providers.get(provider) if isinstance(providers, dict) else None
        pool = provider_status.get("pool") if isinstance(provider_status, dict) else None
        keys = pool.get("keys") if isinstance(pool, dict) else None
        target = next(
            (
                item
                for item in keys or []
                if isinstance(item, dict) and PortalUseCase._status_key_index(item) == index
            ),
            None,
        )
        if target is None:
            raise ValueError("找不到指定的上游金鑰")
        if not target.get("quarantined"):
            raise ValueError("指定的上游金鑰目前不在隔離中")

    @staticmethod
    def _status_key_index(item: dict[str, Any]) -> int | None:
        try:
            return int(item.get("index", -1))
        except (TypeError, ValueError):
            return None

    def create_class(self, teacher_id: int, name: str, ends_at: str | None, api_key_ttl_hours: int | None) -> dict[str, Any]:
        self._assert_teacher(teacher_id)
        return self.repo.create_class(teacher_id, name, ends_at, api_key_ttl_hours)

    def list_classes(self, user_id: int) -> list[dict[str, Any]]:
        self._assert_teacher(user_id)
        return self.repo.list_classes(teacher_id=user_id)

    def create_session(
        self,
        teacher_id: int,
        class_id: int,
        name: str,
        ttl_hours: int | None = None,
        session_at: str | None = None,
        invocation_channel: str | None = None,
        invocation_arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_teacher(teacher_id)
        klass = self.repo.get_class(class_id)
        if not klass or klass["teacher_id"] != teacher_id:
            raise PermissionError("class not owned by teacher")
        arguments = invocation_arguments or self._create_session_arguments(
            name=name,
            ttl_hours=ttl_hours,
            session_at=session_at,
        )
        session = self.repo.create_class_session(
            class_id,
            teacher_id,
            name,
            ttl_hours=ttl_hours,
            session_at=session_at,
            agent_action_audit=self._agent_action_audit(
                actor_user_id=teacher_id,
                action="create_class_session",
                class_id=class_id,
                session_id=None,
                arguments=arguments,
                invocation_channel=invocation_channel,
            ),
        )
        return session

    def list_sessions(self, user_id: int, class_id: int) -> list[dict[str, Any]]:
        self._assert_class_owner_or_admin(user_id, class_id)
        return self.repo.list_class_sessions(class_id)

    def get_session(
        self, user_id: int, class_id: int, session_id: int
    ) -> dict[str, Any] | None:
        return next(
            (
                session
                for session in self.list_sessions(user_id, class_id)
                if int(session["id"]) == session_id
            ),
            None,
        )

    def update_session(
        self,
        user_id: int,
        class_id: int,
        session_id: int,
        expires_at: str | None = None,
        name: str | None = None,
        image_generation_enabled: bool | None = None,
        tts_enabled: bool | None = None,
        speech_transcription_enabled: bool | None = None,
        prompt_logging_enabled: bool | None = None,
        status: str | None = None,
        course_catalog_yaml: str | None = None,
        seat_limit: int | None = None,
        invocation_channel: str | None = None,
        invocation_arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        # Class owner or admin may update any session fields (privileged and non-privileged).
        # Admins must be allowed for non-privileged-only updates too, so permission stays consistent.
        self._assert_class_owner_or_admin(user_id, class_id)
        if status is not None and status not in _VALID_SESSION_STATUSES:
            raise ValueError("invalid session status")
        if seat_limit is not None and (
            not isinstance(seat_limit, int)
            or isinstance(seat_limit, bool)
            or seat_limit < 1
        ):
            raise ValueError("座位上限必須為正整數")
        changes = invocation_arguments or self._session_change_arguments(
            expires_at=expires_at,
            name=name,
            image_generation_enabled=image_generation_enabled,
            tts_enabled=tts_enabled,
            speech_transcription_enabled=speech_transcription_enabled,
            prompt_logging_enabled=prompt_logging_enabled,
            status=status,
            course_catalog_yaml=course_catalog_yaml,
            seat_limit=seat_limit,
        )
        session = self.repo.update_class_session(
            class_id,
            session_id,
            expires_at=expires_at,
            name=name,
            image_generation_enabled=image_generation_enabled,
            tts_enabled=tts_enabled,
            speech_transcription_enabled=speech_transcription_enabled,
            prompt_logging_enabled=prompt_logging_enabled,
            status=status,
            course_catalog_yaml=course_catalog_yaml,
            seat_limit=seat_limit,
            agent_action_audit=self._agent_action_audit(
                actor_user_id=user_id,
                action=self._session_action(changes),
                class_id=class_id,
                session_id=session_id,
                arguments=changes,
                invocation_channel=invocation_channel,
            ),
        )
        return session

    @staticmethod
    def _agent_action_audit(
        *,
        actor_user_id: int,
        action: str,
        class_id: int,
        session_id: int | None,
        arguments: dict[str, Any],
        invocation_channel: str | None,
    ) -> AgentActionAudit | None:
        if invocation_channel != "webmcp":
            return None
        return AgentActionAudit(
            actor_user_id=actor_user_id,
            action=action,
            class_id=class_id,
            session_id=session_id,
            arguments=arguments,
            invocation_channel=invocation_channel,
        )

    @staticmethod
    def _create_session_arguments(
        *,
        name: str,
        ttl_hours: int | None,
        session_at: str | None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"name": name.strip()}
        if session_at is not None:
            arguments["session_at"] = session_at
        if ttl_hours is not None:
            arguments["ttl_hours"] = ttl_hours
        return arguments

    @staticmethod
    def _session_change_arguments(**changes: Any) -> dict[str, Any]:
        return {key: value for key, value in changes.items() if value is not None}

    @staticmethod
    def _session_action(changes: dict[str, Any]) -> str:
        fields = set(changes)
        if fields and fields <= _SESSION_CAPABILITY_FIELDS:
            return "update_session_capabilities"
        if fields == {"expires_at"}:
            return "change_session_expiry"
        if fields == {"seat_limit"}:
            return "change_session_seat_limit"
        return "update_class_session"

    def extension_course_catalog(self, api_key: str) -> dict[str, str]:
        yaml_text = self.repo.get_course_catalog_yaml_for_api_key(api_key)
        if yaml_text is None:
            raise PermissionError("無效的 Classroom API Key")
        return {"course_catalog_yaml": yaml_text}

    def redeem(self, user_id: int, invite_code: str) -> dict[str, Any]:
        return self.repo.redeem_invite(invite_code, user_id)

    def issue_extension_handoff(self, user_id: int) -> str:
        return self._handoff_service().create_token(user_id)

    def redeem_with_handoff(self, handoff_token: str, invite_code: str) -> dict[str, Any]:
        user_id = self._handoff_service().consume_token(handoff_token)
        return self.repo.redeem_invite(invite_code, user_id)

    def redeem_with_nickname(self, invite_code: str, nickname: str) -> dict[str, Any]:
        cleaned = (nickname or "").strip()
        if not cleaned:
            raise ValueError("classroom nickname is required")
        if len(cleaned) > _NICKNAME_MAX_LEN:
            raise ValueError("classroom nickname is too long")
        return self.repo.redeem_invite_with_nickname(invite_code, cleaned)

    def chat_language_models_template(self) -> list[dict[str, Any]]:
        return load_vans_template()

    def _handoff_service(self) -> ExtensionHandoffService:
        return ExtensionHandoffService(
            session_secret=self.settings.auth.session_secret,
            try_mark_nonce_used=self.repo.try_consume_handoff_nonce,
        )

    def redemptions(self, teacher_id: int, class_id: int) -> list[dict[str, Any]]:
        self._assert_class_owner_or_admin(teacher_id, class_id)
        return self.repo.list_session_redemptions(class_id)

    def update_class_member_status(
        self, actor_id: int, class_id: int, user_id: int, status: str
    ) -> dict[str, Any]:
        self._assert_class_owner_or_admin(actor_id, class_id)
        if status not in _VALID_STATUSES:
            raise ValueError("狀態無效")
        updated = self.repo.set_class_member_user_status(class_id, user_id, status)
        if updated is None:
            raise ValueError("此學生不在本課程中")
        return updated

    def prompt_logs(
        self,
        teacher_id: int,
        class_id: int,
        session_id: int | None,
        keyword: str | None,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> dict[str, Any]:
        self._assert_class_owner(teacher_id, class_id)
        has_filter = any([session_id, keyword, start_at, end_at])
        limit = 100 if has_filter else 10
        items = self.repo.list_prompt_logs(
            teacher_id,
            class_id,
            session_id,
            keyword,
            start_at,
            end_at,
            limit=limit,
        )
        public_items = [{key: value for key, value in item.items() if key != "raw_prompt"} for item in items]
        return {"items": public_items, "limit": limit, "has_filter": has_filter}

    def prompt_log_detail(self, teacher_id: int, class_id: int, log_id: int) -> dict[str, Any] | None:
        self._assert_class_owner(teacher_id, class_id)
        return self.repo.get_prompt_log(teacher_id, class_id, log_id)

    def class_usage(self, teacher_id: int, class_id: int) -> list[dict[str, Any]]:
        self._assert_class_owner(teacher_id, class_id)
        return self.repo.class_usage(teacher_id, class_id)

    def admin_users(self, user_id: int) -> list[dict[str, Any]]:
        self._assert_admin(user_id)
        return self.repo.list_users()

    def admin_update_user(
        self,
        admin_id: int,
        user_id: int,
        role: str | None,
        status: str | None,
        roles: list[str] | None = None,
    ) -> dict[str, Any] | None:
        self._assert_admin(admin_id)
        if roles is not None:
            invalid = [item for item in roles if item not in _VALID_ROLES]
            if invalid:
                raise ValueError(f"invalid roles: {', '.join(invalid)}")
        if status is not None and status not in _VALID_STATUSES:
            raise ValueError("invalid status")
        return self.repo.update_user(user_id, role=role, status=status, roles=roles)

    def admin_classes(self, user_id: int) -> list[dict[str, Any]]:
        self._assert_admin(user_id)
        return self.repo.list_classes()

    def admin_update_class(self, user_id: int, class_id: int, status: str) -> dict[str, Any] | None:
        self._assert_admin(user_id)
        return self.repo.set_class_status(class_id, status)

    def admin_settings(self, user_id: int) -> dict[str, Any]:
        self._assert_admin(user_id)
        return settings_summary(self.settings)

    def admin_update_settings(
        self,
        user_id: int,
        archive_after_days: int | None = None,
        delete_after_days: int | None = None,
        student_default_ttl_hours: int | None = None,
        open_registration: bool | None = None,
    ) -> dict[str, Any]:
        self._assert_admin(user_id)
        self.repo.update_runtime_settings(
            archive_after_days=archive_after_days,
            delete_after_days=delete_after_days,
            student_default_ttl_hours=student_default_ttl_hours,
            open_registration=open_registration,
        )
        self.refresh_settings()
        return settings_summary(self.settings)

    def admin_run_archive(self, user_id: int, now: datetime | None = None) -> dict[str, Any]:
        self._assert_admin(user_id)
        archived = self.repo.archive_prompt_logs(
            now=now,
            archive_after_days=self.settings.prompt_logs.archive_after_days,
        )
        purged = self.repo.purge_archived_prompt_logs(
            now=now,
            delete_after_days=self.settings.prompt_logs.delete_after_days,
        )
        return {"archived": archived.get("archived", 0), "deleted": purged.get("deleted", 0)}

    def admin_clear_archive(self, user_id: int) -> dict[str, Any]:
        self._assert_admin(user_id)
        return self.repo.clear_all_archived_prompt_logs()

    def admin_prompt_log_usage(self, user_id: int) -> list[dict[str, Any]]:
        self._assert_admin(user_id)
        return self.repo.prompt_log_usage_by_user()

    def admin_delete_user_prompt_logs(self, user_id: int, target_user_ids: list[int]) -> dict[str, Any]:
        self._assert_admin(user_id)
        ids = [int(value) for value in target_user_ids]
        if not ids:
            raise ValueError("user_ids required")
        return self.repo.delete_prompt_logs_for_users(ids)

    def _assert_teacher(self, user_id: int) -> None:
        user = self.repo.get_user(user_id)
        if not user or not (self._has_role(user, "teacher") or self._has_role(user, "admin")):
            raise PermissionError("teacher only")

    def _assert_admin(self, user_id: int) -> None:
        user = self.repo.get_user(user_id)
        if not user or not self._has_role(user, "admin"):
            raise PermissionError("admin only")

    def _assert_class_owner(self, teacher_id: int, class_id: int) -> None:
        self._assert_teacher(teacher_id)
        klass = self.repo.get_class(class_id)
        if not klass:
            raise MissingTargetError("找不到課程")
        if klass["teacher_id"] != teacher_id:
            raise PermissionError("class not owned by teacher")

    def _assert_class_owner_or_admin(self, user_id: int, class_id: int) -> None:
        user = self.repo.get_user(user_id)
        if not user:
            raise PermissionError("teacher only")
        if self._has_role(user, "admin"):
            klass = self.repo.get_class(class_id)
            if not klass:
                raise MissingTargetError("找不到課程")
            return
        self._assert_class_owner(user_id, class_id)

    def _has_role(self, user: dict[str, Any], role: str) -> bool:
        return role in set(user.get("roles") or [user.get("role")])
