from datetime import datetime
from typing import Any

from src.infrastructure.config import RouterSettings, settings_summary, update_non_secret_settings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository


class PortalUseCase:
    def __init__(self, repo: SqliteRouterRepository, settings: RouterSettings):
        self.repo = repo
        self.settings = settings

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

    def list_sessions(self, teacher_id: int, class_id: int) -> list[dict[str, Any]]:
        self._assert_class_owner(teacher_id, class_id)
        return self.repo.list_class_sessions(class_id)

    def update_session(
        self,
        teacher_id: int,
        class_id: int,
        session_id: int,
        expires_at: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any] | None:
        self._assert_class_owner(teacher_id, class_id)
        return self.repo.update_class_session(class_id, session_id, expires_at=expires_at, name=name)

    def redeem(self, user_id: int, invite_code: str) -> dict[str, Any]:
        return self.repo.redeem_invite(invite_code, user_id)

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
        retention_days: int | None = None,
        student_default_ttl_hours: int | None = None,
        open_registration: bool | None = None,
    ) -> dict[str, Any]:
        self._assert_admin(user_id)
        if not self.settings.path:
            raise ValueError("missing config path")
        updated = update_non_secret_settings(
            self.settings.path,
            retention_days=retention_days,
            student_default_ttl_hours=student_default_ttl_hours,
            open_registration=open_registration,
        )
        return settings_summary(updated)

    def admin_run_archive(self, user_id: int, now: datetime | None = None) -> dict[str, Any]:
        self._assert_admin(user_id)
        return self.repo.archive_prompt_logs(now=now, retention_days=self.settings.prompt_logs.retention_days)

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

    def _has_role(self, user: dict[str, Any], role: str) -> bool:
        return role in set(user.get("roles") or [user.get("role")])
