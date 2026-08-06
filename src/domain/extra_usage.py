from __future__ import annotations

from typing import Any

from src.domain.errors import extract_upstream_error_text

DEFAULT_EXTRA_USAGE_MESSAGE = "extra usage balance is empty, add extra usage"

def is_extra_usage_exhaustion(status_code: int, body: Any) -> bool:
    """True when the upstream response is Extra Usage Exhaustion (402 + markers)."""
    if status_code != 402:
        return False
    text = (extract_upstream_error_text(body) or "").lower()
    return "extra usage" in text
