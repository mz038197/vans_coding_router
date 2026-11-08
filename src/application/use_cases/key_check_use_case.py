"""Key Check: a Partner Service's question about one key (ADR 0077, 0082, 0083).

The answer reuses the same key verification `/v1/*` uses, so a key gets the same
verdict on the router and on every Partner Service.
"""

from __future__ import annotations

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


def _refusal(reason: str) -> dict[str, Any]:
    return {"accepted": False, "reason": reason, "message": REFUSAL_NOTICES[reason]}


class KeyCheckUseCase:
    def __init__(self, api_key_repo: RouterRepositoryPort):
        self.api_key_repo = api_key_repo

    def check(self, api_key: str) -> dict[str, Any]:
        context, failure = self.api_key_repo.verify_api_key_with_reason(api_key)
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
        }

    def _personal_answer(self, context: AuthContext) -> dict[str, Any]:
        # `is_admin` comes from the role table, never `users.role` (ADR 0078). An admin
        # may manage every Class, ended ones included; anyone else the Classes they own
        # (ADR 0083). Each Class carries only its id and name.
        is_admin = bool(context.is_admin)
        user_id = int(context.user_id)
        rows = self.api_key_repo.list_classes(teacher_id=None if is_admin else user_id)
        classes = sorted(
            ({"id": int(row["id"]), "name": str(row["name"])} for row in rows),
            key=lambda item: item["id"],
        )
        return {
            "accepted": True,
            "kind": "personal",
            "user_id": user_id,
            "is_admin": is_admin,
            "classes": classes,
        }
