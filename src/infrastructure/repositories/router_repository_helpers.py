from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def prompt_log_messages(messages_json: str | None, raw_prompt: str | None) -> list[dict[str, Any]]:
    if messages_json:
        try:
            parsed = json.loads(messages_json)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    if raw_prompt:
        return [{"role": "user", "content": raw_prompt}]
    return []
