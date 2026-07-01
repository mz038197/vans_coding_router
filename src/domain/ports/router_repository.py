from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from src.domain.entities.auth import AuthContext


class RouterRepositoryPort(Protocol):
    def is_enabled(self) -> bool:
        ...

    def verify_api_key(self, api_key: str) -> tuple[bool, str | None]:
        ...

    def verify_api_key_context(self, api_key: str) -> AuthContext | None:
        ...

    def upsert_google_user(self, email: str, name: str, google_sub: str | None = None) -> dict[str, Any]:
        ...

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        ...

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        ...

    def list_users(self) -> list[dict[str, Any]]:
        ...

    def update_user(
        self,
        user_id: int,
        role: str | None = None,
        status: str | None = None,
        roles: list[str] | None = None,
    ) -> dict[str, Any] | None:
        ...

    def issue_long_lived_key(self, user_id: int) -> str:
        ...

    def get_active_keys(self, user_id: int) -> list[dict[str, Any]]:
        ...

    def create_class(
        self,
        teacher_id: int,
        name: str,
        ends_at: str | None,
        api_key_ttl_hours: int | None = None,
    ) -> dict[str, Any]:
        ...

    def get_class(self, class_id: int) -> dict[str, Any] | None:
        ...

    def list_classes(self, teacher_id: int | None = None) -> list[dict[str, Any]]:
        ...

    def set_class_status(self, class_id: int, status: str) -> dict[str, Any] | None:
        ...

    def create_class_session(
        self,
        class_id: int,
        created_by: int,
        name: str,
        ttl_hours: int | None = None,
        session_at: str | None = None,
    ) -> dict[str, Any]:
        ...

    def list_class_sessions(self, class_id: int) -> list[dict[str, Any]]:
        ...

    def update_class_session(
        self,
        class_id: int,
        session_id: int,
        expires_at: str | None = None,
        name: str | None = None,
        image_generation_enabled: bool | None = None,
        tts_enabled: bool | None = None,
        prompt_logging_enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        ...

    def is_image_generation_enabled(self, session_id: int) -> bool:
        ...

    def is_tts_enabled(self, session_id: int) -> bool:
        ...

    def is_prompt_logging_enabled(self, session_id: int) -> bool:
        ...

    def redeem_invite(self, invite_code: str, user_id: int) -> dict[str, Any]:
        ...

    def list_session_redemptions(self, class_id: int) -> list[dict[str, Any]]:
        ...

    def log_prompt(
        self,
        auth: AuthContext | None,
        raw_prompt: str,
        final_prompt: str,
        model: str,
        status: str,
        client_ip: str | None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        message_preview: str = "",
        messages_json: str = "",
        api_endpoint: str = "",
        response_preview: str = "",
    ) -> None:
        ...

    def class_usage(self, teacher_id: int, class_id: int) -> list[dict[str, Any]]:
        ...

    def list_prompt_logs(
        self,
        teacher_id: int,
        class_id: int,
        session_id: int | None = None,
        keyword: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        ...

    def get_prompt_log(self, teacher_id: int, class_id: int, log_id: int) -> dict[str, Any] | None:
        ...

    def get_runtime_settings(self) -> dict[str, str]:
        ...

    def update_runtime_settings(
        self,
        retention_days: int | None = None,
        student_default_ttl_hours: int | None = None,
        open_registration: bool | None = None,
    ) -> dict[str, str]:
        ...

    def archive_prompt_logs(self, now: datetime | None = None, retention_days: int | None = None) -> dict[str, Any]:
        ...
