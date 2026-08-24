from __future__ import annotations

import json
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


def _body_blob(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    try:
        return json.dumps(body)
    except TypeError:
        return str(body)


def is_credit_exhaustion(status_code: int, body: Any) -> bool:
    """True when the upstream response is Credit Exhaustion (402 + credit markers)."""
    if status_code != 402:
        return False
    blob = _body_blob(body).lower()
    return "insufficient credits" in blob or "payment_required" in blob


def is_key_failover_exhaustion(status_code: int, body: Any) -> bool:
    """True when Key Failover should run (Extra Usage Exhaustion or Credit Exhaustion)."""
    return is_extra_usage_exhaustion(status_code, body) or is_credit_exhaustion(status_code, body)
