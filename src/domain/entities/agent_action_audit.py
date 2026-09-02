from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentActionAudit:
    actor_user_id: int
    action: str
    class_id: int | None
    session_id: int | None
    arguments: dict[str, Any]
    invocation_channel: str
