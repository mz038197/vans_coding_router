from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from src.domain.entities.agent_action_audit import AgentActionAudit
from src.domain.entities.auth import AuthContext, PortalSessionContext
from src.domain.session_model_allowlist import MODEL_ALLOWLIST_UNCHANGED


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

    def create_portal_session(
        self,
        user_id: int,
        browser_description: str,
        now: datetime | None = None,
    ) -> tuple[str, PortalSessionContext]:
        ...

    def authenticate_portal_session(
        self,
        token: str,
        now: datetime | None = None,
        refresh_activity: bool = True,
    ) -> PortalSessionContext | None:
        ...

    def list_portal_sessions(
        self,
        user_id: int,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def revoke_portal_session(
        self,
        user_id: int,
        session_id: int,
        reason: str,
        actor_user_id: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        ...

    def revoke_other_portal_sessions(
        self,
        user_id: int,
        current_session_id: int,
        reason: str,
        now: datetime | None = None,
    ) -> int:
        ...

    def revoke_all_portal_sessions(
        self,
        user_id: int,
        reason: str,
        actor_user_id: int | None = None,
        now: datetime | None = None,
    ) -> int:
        ...

    def purge_portal_sessions(
        self,
        now: datetime | None = None,
        retention_days: int = 30,
    ) -> int:
        ...

    def record_agent_action_audit(
        self,
        actor_user_id: int,
        action: str,
        class_id: int | None,
        session_id: int | None,
        arguments: dict[str, Any],
        invocation_channel: str,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        ...

    def list_agent_action_audits(
        self,
        *,
        actor_user_id: int | None = None,
        class_id: int | None = None,
        session_id: int | None = None,
        action: str | None = None,
        invocation_channel: str | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
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
        agent_action_audit: AgentActionAudit | None = None,
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
        speech_transcription_enabled: bool | None = None,
        prompt_logging_enabled: bool | None = None,
        status: str | None = None,
        course_catalog_yaml: str | None = None,
        seat_limit: int | None = None,
        model_allowlist: Any = MODEL_ALLOWLIST_UNCHANGED,
        agent_action_audit: AgentActionAudit | None = None,
    ) -> dict[str, Any] | None:
        ...

    def get_session_model_allowlist(self, session_id: int) -> list[str] | None:
        ...

    def classroom_api_key_session_allowlist(
        self, api_key: str
    ) -> tuple[bool, list[str] | None]:
        ...

    def get_course_catalog_yaml_for_api_key(self, api_key: str) -> str | None:
        """Return Session Course Catalog YAML for a Classroom API Key.

        Ignores session/key expiry so ended sittings still serve the last catalog.
        Returns None when the key is missing, disabled, or not bound to a session.
        """
        ...

    def is_image_generation_enabled(self, session_id: int) -> bool:
        ...

    def is_tts_enabled(self, session_id: int) -> bool:
        ...

    def is_speech_transcription_enabled(self, session_id: int) -> bool:
        ...

    def is_prompt_logging_enabled(self, session_id: int) -> bool:
        ...

    def redeem_invite(self, invite_code: str, user_id: int) -> dict[str, Any]:
        ...

    def redeem_invite_with_nickname(self, invite_code: str, nickname: str) -> dict[str, Any]:
        """Exchange an Invite Code plus Classroom Nickname for a session key."""
        ...

    def try_consume_handoff_nonce(self, nonce: str) -> bool:
        """Mark a Sign-in Handoff nonce as used. Returns False if already used."""
        ...

    def list_session_redemptions(self, class_id: int) -> list[dict[str, Any]]:
        ...

    def set_class_member_user_status(
        self, class_id: int, user_id: int, status: str
    ) -> dict[str, Any] | None:
        """Set users.status for a class member. Returns None if the user is not in the class."""
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
        archive_after_days: int | None = None,
        delete_after_days: int | None = None,
        student_default_ttl_hours: int | None = None,
        open_registration: bool | None = None,
    ) -> dict[str, str]:
        ...

    def archive_prompt_logs(self, now: datetime | None = None, archive_after_days: int | None = None) -> dict[str, Any]:
        ...

    def purge_archived_prompt_logs(
        self, now: datetime | None = None, delete_after_days: int | None = None
    ) -> dict[str, Any]:
        ...

    def clear_all_archived_prompt_logs(self) -> dict[str, Any]:
        ...

    def prompt_log_usage_by_user(self) -> list[dict[str, Any]]:
        ...

    def delete_prompt_logs_for_users(self, user_ids: list[int]) -> dict[str, Any]:
        ...
