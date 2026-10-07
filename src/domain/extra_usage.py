from __future__ import annotations

import calendar
import json
import math
from datetime import datetime, timezone
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


def extra_usage_remaining_from_usage_payload(payload: Any) -> float | None:
    """Return Extra Usage Remaining from an Ollama usage document, or None if unknown.

    Session/weekly included usage, credits, and activity cost are not Extra Usage Remaining.
    Zero is a valid remaining amount.
    """
    if not isinstance(payload, dict):
        return None
    for raw in _extra_usage_remaining_candidates(payload):
        parsed = _as_finite_number(raw)
        if parsed is not None:
            return parsed
    return None


def account_credit_remaining_from_credits_payload(payload: Any) -> float | None:
    """Return Account Credit Remaining (dollars) from an OpenRouter credits document.

    Zero and a negative amount are valid. A per-key spending cap and that key's own
    usage are not this balance.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    credits = _as_finite_number(data.get("total_credits"))
    usage = _as_finite_number(data.get("total_usage"))
    if credits is None or usage is None:
        return None
    return credits - usage


# Published included monthly amounts. Ollama's usage document has spend, not this cap.
_INCLUDED_USD_BY_PLAN = {
    "pro": 60.0,
    "max": 300.0,
    "team": 1000.0,
}

_SECOND = 1
_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY
_MONTH = 30 * _DAY
_YEAR = 365 * _DAY
# Same cutoffs as dustin/go-humanize RelTime, without the ago/from-now suffix.
_RELATIVE_MAGNITUDES: tuple[tuple[int, str, int], ...] = (
    (_SECOND, "now", _SECOND),
    (2 * _SECOND, "1 second", 1),
    (_MINUTE, "{n} seconds", _SECOND),
    (2 * _MINUTE, "1 minute", 1),
    (_HOUR, "{n} minutes", _MINUTE),
    (2 * _HOUR, "1 hour", 1),
    (_DAY, "{n} hours", _HOUR),
    (2 * _DAY, "1 day", 1),
    (_WEEK, "{n} days", _DAY),
    (2 * _WEEK, "1 week", 1),
    (_MONTH, "{n} weeks", _WEEK),
    (2 * _MONTH, "1 month", 1),
    (_YEAR, "{n} months", _MONTH),
    (2 * _YEAR, "1 year", 1),
    (10**18, "{n} years", _YEAR),
)


def included_monthly_usage_from_documents(
    usage_payload: Any,
    account_payload: Any,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """Return the settings-page Included Monthly Usage meter for one Ollama key.

    `summary` is `$X of $Y used`. `resets` is `Resets in …`. Spend is the sum of
    daily `usage_usd` in the current subscription month. The cap comes from the
    plan name. The month boundary is the monthly anniversary of the account's
    subscription anchor. Zero spend is valid.
    """
    if not isinstance(usage_payload, dict) or not isinstance(account_payload, dict):
        return None
    plan = account_payload.get("Plan", account_payload.get("plan"))
    if not isinstance(plan, str):
        return None
    included = _INCLUDED_USD_BY_PLAN.get(plan.strip().lower())
    anchor = _subscription_anchor(account_payload)
    window_start = _parse_time(usage_payload.get("from"))
    if included is None or anchor is None or window_start is None:
        return None
    now_utc = now.astimezone(timezone.utc)
    period_start = _period_start(anchor, now_utc)
    if window_start.date() > period_start.date():
        return None
    buckets = usage_payload.get("buckets")
    if not isinstance(buckets, list):
        return None
    used = 0.0
    for bucket in buckets:
        if not isinstance(bucket, dict):
            return None
        bucket_start = _parse_time(bucket.get("from"))
        if bucket_start is None or bucket_start.date() < period_start.date():
            continue
        amount = _as_finite_number(bucket.get("usage_usd"))
        if amount is None:
            return None
        used += amount
    resets_at = _next_monthly_instant(anchor, now_utc)
    return {
        "used_usd": used,
        "included_usd": included,
        "resets_at": _iso_z(resets_at),
        "summary": f"${_format_dollars(used)} of ${_format_dollars(included)} used",
        "resets": f"Resets in {_relative_phrase(int((resets_at - now_utc).total_seconds()))}.",
    }


def _subscription_anchor(account: dict[str, Any]) -> datetime | None:
    """Subscription anniversary. Account CreatedAt is not this instant."""
    for key in ("SubscriptionRenewsAt", "renews_at"):
        parsed = _parse_time(account.get(key))
        if parsed is not None:
            return parsed
    return None


def _period_start(anchor: datetime, now: datetime) -> datetime:
    renewal = _next_monthly_instant(anchor, now)
    year, month = _shift_month(renewal.year, renewal.month, -1)
    return _on_month(anchor, year, month)


def _next_monthly_instant(anchor: datetime, now: datetime) -> datetime:
    candidate = _on_month(anchor, now.year, now.month)
    if candidate <= now:
        year, month = _shift_month(now.year, now.month, 1)
        candidate = _on_month(anchor, year, month)
    return candidate


def _on_month(anchor: datetime, year: int, month: int) -> datetime:
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _relative_phrase(delta_seconds: int) -> str:
    diff = abs(delta_seconds)
    for limit, template, div in _RELATIVE_MAGNITUDES:
        if diff <= limit:
            if "{n}" not in template:
                return template
            return template.format(n=diff // div)
    return "now"


def _format_dollars(amount: float) -> str:
    rounded = round(amount, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}"


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extra_usage_remaining_candidates(payload: dict[str, Any]) -> list[Any]:
    candidates: list[Any] = []
    if "extra_usage_remaining" in payload:
        candidates.append(payload["extra_usage_remaining"])
    extra = payload.get("extra_usage")
    if isinstance(extra, dict) and "remaining" in extra:
        candidates.append(extra["remaining"])
    return candidates


def _as_finite_number(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) else None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    return None
