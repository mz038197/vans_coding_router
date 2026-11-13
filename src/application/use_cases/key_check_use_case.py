"""Key Check: a Partner Service's question about one key (ADR 0077, 0082, 0083, 0095).

The answer reuses the same key verification `/v1/*` uses, so a key gets the same
verdict on the router and on every Partner Service.

Teacher Classes (ADR 0094) is the same Partner Service's question about one user id:
which Classes that user may manage, answered as the Personal API Key answer names them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from src.domain.entities.auth import AuthContext
from src.domain.errors import ApiKeyExpiredError, ApiKeyNotStartedError, AuthenticationError
from src.domain.ports.router_repository import RouterRepositoryPort

# One cause code, one notice. The router owns every notice (ADR 0082); the texts are
# the ones `/v1/*` already shows for the same cause.
REFUSAL_NOTICES: dict[str, str] = {
    "invalid": AuthenticationError().message,
    "disabled": AuthenticationError().message,
    "expired": ApiKeyExpiredError().message,
    "not_started": ApiKeyNotStartedError().message,
}


# A Key Check writes a key's `last_used_at` at most once in this interval (ADR 0077).
LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# A Teacher Classes refusal: the user is unknown, disabled, or neither teacher nor admin.
NOT_A_TEACHER_REFUSAL: dict[str, Any] = {
    "accepted": False,
    "reason": "not_a_teacher",
    "message": "此帳號不是教師或管理員",
}


def _refusal(reason: str) -> dict[str, Any]:
    return {"accepted": False, "reason": reason, "message": REFUSAL_NOTICES[reason]}


def _display_name(context: AuthContext) -> str:
    # The holder's `users.name`: the Classroom Nickname for a nickname student, the
    # Google name otherwise (ADR 0095). Never the email.
    return context.name or ""


class KeyCheckUseCase:
    def __init__(
        self,
        api_key_repo: RouterRepositoryPort,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.api_key_repo = api_key_repo
        self.clock = clock

    def check(self, api_key: str) -> dict[str, Any]:
        context, failure = self.api_key_repo.verify_api_key_with_reason(
            api_key,
            now=self.clock(),
            last_used_write_interval=LAST_USED_WRITE_INTERVAL,
        )
        if context is None:
            # `missing` (empty or whitespace key) and any cause without its own code
            # are answered as `invalid` (ADR 0083).
            return _refusal(failure if failure in REFUSAL_NOTICES else "invalid")
        if context.session_id is None:
            return self._personal_answer(context)
        return {
            "accepted": True,
            "kind": "classroom",
            "student_id": int(context.user_id),
            "class_id": int(context.class_id),
            "class_session_id": int(context.session_id),
            "display_name": _display_name(context),
        }

    def teacher_classes(self, user_id: int) -> dict[str, Any]:
        """The Classes an active teacher or admin may manage (ADR 0094).

        Standing comes from the role table only, as for `is_admin` (ADR 0078).
        """
        user = self.api_key_repo.get_user(user_id)
        if user is None or user.get("status") != "active":
            return dict(NOT_A_TEACHER_REFUSAL)
        roles = self.api_key_repo.role_table_roles(user_id)
        if "admin" not in roles and "teacher" not in roles:
            return dict(NOT_A_TEACHER_REFUSAL)
        is_admin = "admin" in roles
        return {
            "accepted": True,
            "user_id": user_id,
            "is_admin": is_admin,
            "classes": self._managed_classes(user_id, is_admin),
        }

    def _managed_classes(self, user_id: int, is_admin: bool) -> list[dict[str, Any]]:
        # An admin may manage every Class, ended ones included; anyone else the
        # Classes they own (ADR 0083). Each Class carries only its id and name.
        rows = self.api_key_repo.list_classes(teacher_id=None if is_admin else user_id)
        return sorted(
            ({"id": int(row["id"]), "name": str(row["name"])} for row in rows),
            key=lambda item: item["id"],
        )

    def _personal_answer(self, context: AuthContext) -> dict[str, Any]:
        # `is_admin` comes from the role table, never `users.role` (ADR 0078): a user
        # with no role rows is not an admin, whatever `users.role` says.
        user_id = int(context.user_id)
        is_admin = "admin" in self.api_key_repo.role_table_roles(user_id)
        return {
            "accepted": True,
            "kind": "personal",
            "user_id": user_id,
            "display_name": _display_name(context),
            "is_admin": is_admin,
            "classes": self._managed_classes(user_id, is_admin),
        }
