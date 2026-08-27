from datetime import datetime
from typing import Any

from src.domain.ports.router_repository import RouterRepositoryPort
from src.infrastructure.auth.extension_handoff import ExtensionHandoffService
from src.infrastructure.config import RouterSettings, apply_runtime_settings, settings_summary
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template

_VALID_ROLES = frozenset({"admin", "teacher", "student"})
_VALID_STATUSES = frozenset({"active", "inactive"})
_VALID_SESSION_STATUSES = frozenset({"active", "ended"})
_NICKNAME_MAX_LEN = 64


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
        self.refresh_settings()

    def refresh_settings(self) -> None:
        self.settings = apply_runtime_settings(self._base_settings, self.repo.get_runtime_settings())
        self.repo.settings = self.settings

    def google_login(self, email: str, name: str, google_sub: str | None = None) -> dict[str, Any]:
        existing = self.repo.get_user_by_email(email)
        if not existing and not self.settings.auth.open_registration:
            raise ValueError("尚未開放註冊")
        return self.repo.upsert_google_user(email=email, name=name, google_sub=google_sub)

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

    async def release_key_quarantine(self, user_id: int, provider: str, index: int) -> dict[str, Any]:
        self._assert_teacher(user_id)
        gateway = self._llm_gateway
        if gateway is None:
            raise ValueError("上游 gateway 未設定")
        release_fn = getattr(gateway, "release_key_quarantine", None)
        if not callable(release_fn):
            raise ValueError("此 gateway 不支援解除隔離")
        try:
            await release_fn(provider, index)
        except (KeyError, IndexError) as exc:
            raise ValueError(str(exc)) from exc
        return {"ok": True, "provider": provider, "index": index}

    def create_class(self, teacher_id: int, name: str, ends_at: str | None, api_key_ttl_hours: int | None) -> dict[str, Any]:
        self._assert_teacher(teacher_id)
        return self.repo.create_class(teacher_id, name, ends_at, api_key_ttl_hours)

    def create_session(
        self,
        teacher_id: int,
        class_id: int,
        name: str,
        ttl_hours: int | None = None,
        session_at: str | None = None,
    ) -> dict[str, Any]:
        self._assert_teacher(teacher_id)
        klass = self.repo.get_class(class_id)
        if not klass or klass["teacher_id"] != teacher_id:
            raise PermissionError("class not owned by teacher")
        return self.repo.create_class_session(
            class_id,
            teacher_id,
            name,
            ttl_hours=ttl_hours,
            session_at=session_at,
        )

    def list_sessions(self, user_id: int, class_id: int) -> list[dict[str, Any]]:
        self._assert_class_owner_or_admin(user_id, class_id)
        return self.repo.list_class_sessions(class_id)

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
        return self.repo.update_class_session(
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
        )

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
        self._assert_class_owner(teacher_id, class_id)
        return self.repo.list_session_redemptions(class_id)

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
        if not klass or klass["teacher_id"] != teacher_id:
            raise PermissionError("class not owned by teacher")

    def _assert_class_owner_or_admin(self, user_id: int, class_id: int) -> None:
        user = self.repo.get_user(user_id)
        if not user:
            raise PermissionError("teacher only")
        if self._has_role(user, "admin"):
            klass = self.repo.get_class(class_id)
            if not klass:
                raise PermissionError("class not found")
            return
        self._assert_class_owner(user_id, class_id)

    def _has_role(self, user: dict[str, Any], role: str) -> bool:
        return role in set(user.get("roles") or [user.get("role")])
