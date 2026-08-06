from __future__ import annotations

from typing import Any

from src.domain.errors import extract_upstream_error_text

DEFAULT_EXTRA_USAGE_MESSAGE = "extra usage balance is empty, add extra usage"

# Ollama returns 402 for Extra Usage balance empty, and 429 for plan/session
# usage limit with Extra Usage as the remedy. Generic 429 rate limits must not match.
_EXTRA_USAGE_STATUS_CODES = frozenset({402, 429})


def is_extra_usage_exhaustion(status_code: int, body: Any) -> bool:
    """True when the upstream response is Extra Usage Exhaustion (402/429 + markers)."""
    if status_code not in _EXTRA_USAGE_STATUS_CODES:
        return False
    text = (extract_upstream_error_text(body) or "").lower()
    return "extra usage" in text or "session usage limit" in text
