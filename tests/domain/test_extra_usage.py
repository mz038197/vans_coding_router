from datetime import datetime, timezone

from src.domain.extra_usage import (
    account_credit_remaining_from_credits_payload,
    extra_usage_remaining_from_usage_payload,
    included_monthly_usage_from_documents,
    is_credit_exhaustion,
    is_extra_usage_exhaustion,
)


def test_detects_402_with_extra_usage_balance_empty():
    body = {"error": "extra usage balance is empty, add extra usage"}
    assert is_extra_usage_exhaustion(402, body) is True


def test_detects_402_with_ollama_extra_usage_only_message():
    body = {
        "error": (
            "this model uses extra usage only (not included plan usage) "
            "and your extra usage balance is empty"
        )
    }
    assert is_extra_usage_exhaustion(402, body) is True


def test_detects_429_session_usage_limit_with_extra_usage_remedy():
    body = {
        "error": {
            "message": (
                "you (mz038197) have reached your session usage limit, "
                "upgrade for higher limits: https://ollama.com/upgrade "
                "or add extra usage: https://ollama.com/settings "
                "(ref: aaaf1935-07d7-4284-b8ef-0b8821ea581e)"
            )
        }
    }
    assert is_extra_usage_exhaustion(429, body) is True


def test_detects_429_with_session_usage_limit_marker_only():
    body = {"error": {"message": "you have reached your session usage limit"}}
    assert is_extra_usage_exhaustion(429, body) is True


def test_rejects_402_without_extra_usage_text():
    assert is_extra_usage_exhaustion(402, {"error": "payment required"}) is False


def test_rejects_generic_429_rate_limit_without_markers():
    body = {"error": {"message": "rate limit exceeded, try again later"}}
    assert is_extra_usage_exhaustion(429, body) is False


def test_rejects_500_even_with_extra_usage_text():
    body = {"error": "extra usage balance is empty"}
    assert is_extra_usage_exhaustion(500, body) is False


def test_accepts_json_string_body():
    raw = '{"error":"extra usage balance is empty, add extra usage"}'
    assert is_extra_usage_exhaustion(402, raw) is True


def test_detects_402_with_insufficient_credits():
    body = {
        "error": {
            "code": 402,
            "message": "Insufficient credits. Add more using https://openrouter.ai/credits",
        }
    }
    assert is_credit_exhaustion(402, body) is True
    assert is_extra_usage_exhaustion(402, body) is False


def test_detects_402_with_payment_required_error_type():
    body = {
        "error": {
            "code": 402,
            "message": "Payment required",
            "metadata": {"error_type": "payment_required"},
        }
    }
    assert is_credit_exhaustion(402, body) is True
    assert is_extra_usage_exhaustion(402, body) is False


def test_rejects_429_even_with_insufficient_credits():
    body = {"error": {"message": "Insufficient credits. Add more using https://openrouter.ai/credits"}}
    assert is_credit_exhaustion(429, body) is False


def test_rejects_402_payment_required_without_credit_markers():
    assert is_credit_exhaustion(402, {"error": "payment required"}) is False


def test_detects_402_with_insufficient_credits_in_metadata_only():
    body = {
        "error": {
            "code": 402,
            "message": "Payment required",
            "metadata": {"reason": "insufficient credits"},
        }
    }
    assert is_credit_exhaustion(402, body) is True


def test_maps_extra_usage_remaining_and_treats_zero_as_remaining():
    assert extra_usage_remaining_from_usage_payload({"extra_usage": {"remaining": 12.5}}) == 12.5
    assert extra_usage_remaining_from_usage_payload({"extra_usage": {"remaining": 0}}) == 0.0


def test_does_not_treat_session_weekly_or_activity_cost_as_extra_usage_remaining():
    payload = {
        "activity": {"cost": "9.99"},
        "credits": {"remaining": 40},
        "extra_usage": {"balance": "40.00"},
        "limits": {
            "session": {"usage": 0.1, "models": []},
            "weekly": {"usage": 0.2, "models": []},
        },
    }
    assert extra_usage_remaining_from_usage_payload(payload) is None


def test_maps_settings_meter_and_treats_zero_spend_as_used():
    now = datetime(2026, 10, 7, 9, 22, tzinfo=timezone.utc)
    meter = included_monthly_usage_from_documents(
        {
            "from": "2026-09-07T00:00:00Z",
            "buckets": [
                {"from": "2026-09-20T00:00:00Z", "usage_usd": 18.0},
                {"from": "2026-09-21T00:00:00Z", "usage_usd": 2.14271},
            ],
        },
        {"Plan": "pro", "renews_at": "2026-01-21T01:23:55Z", "Email": "hidden@example.com"},
        now=now,
    )
    assert meter["summary"] == "$2.14 of $60 used"
    assert meter["resets"] == "Resets in 1 week."
    assert meter["resets_at"] == "2026-10-21T01:23:55Z"
    assert "hidden@example.com" not in str(meter)
    zero = included_monthly_usage_from_documents(
        {"from": "2026-09-07T00:00:00Z", "buckets": [{"from": "2026-10-01T00:00:00Z", "usage_usd": 0}]},
        {"Plan": "max", "renews_at": "2026-10-01T00:00:00Z"},
        now=now,
    )
    assert zero["summary"] == "$0 of $300 used"


def test_recovers_anniversary_from_the_settings_meter_for_that_signup():
    now = datetime(2026, 10, 7, 9, 22, tzinfo=timezone.utc)
    usage = {
        "from": "2026-09-07T00:00:00Z",
        "buckets": [
            {"from": "2026-09-19T00:00:00Z", "usage_usd": 5.53},
            {"from": "2026-09-20T00:00:00Z", "usage_usd": 0.2},
            {"from": "2026-09-21T00:00:00Z", "usage_usd": 2.14271},
        ],
    }
    meter = included_monthly_usage_from_documents(
        usage,
        {"Plan": "pro", "CreatedAt": "2026-01-19T06:56:45.74848Z"},
        now=now,
    )
    assert meter["summary"] == "$2.14 of $60 used"
    assert meter["resets"] == "Resets in 1 week."
    assert meter["resets_at"] == "2026-10-21T01:23:55Z"
    later = included_monthly_usage_from_documents(
        {
            "from": "2026-09-07T00:00:00Z",
            "buckets": usage["buckets"] + [{"from": "2026-10-08T00:00:00Z", "usage_usd": 1}],
        },
        {"Plan": "pro", "CreatedAt": "2026-01-19T06:56:45.74848Z"},
        now=datetime(2026, 10, 8, 9, 22, tzinfo=timezone.utc),
    )
    assert later["summary"] == "$3.14 of $60 used"
    assert later["resets_at"] == "2026-10-21T01:23:55Z"
    assert included_monthly_usage_from_documents(
        usage,
        {"Plan": "pro", "CreatedAt": "2026-02-02T00:00:00Z"},
        now=now,
    ) is None


def test_recovers_second_account_anniversary_from_its_settings_meter():
    now = datetime(2026, 10, 7, 10, 6, tzinfo=timezone.utc)
    meter = included_monthly_usage_from_documents(
        {
            "from": "2026-09-07T00:00:00Z",
            "buckets": [
                {"from": "2026-09-16T00:00:00Z", "usage_usd": 40},
                {"from": "2026-09-17T00:00:00Z", "usage_usd": 11.15},
            ],
        },
        {"Plan": "pro", "Name": "vanscoding"},
        now=now,
    )
    assert meter["summary"] == "$11.15 of $60 used"
    assert meter["resets"] == "Resets in 1 week."
    assert meter["resets_at"] == "2026-10-17T12:02:38Z"


def test_rejects_meter_when_plan_or_window_cannot_price_the_month():
    now = datetime(2026, 10, 7, 9, 22, tzinfo=timezone.utc)
    usage = {
        "from": "2026-09-30T00:00:00Z",
        "buckets": [{"from": "2026-10-01T00:00:00Z", "usage_usd": 1}],
    }
    assert included_monthly_usage_from_documents(
        usage,
        {"Plan": "free", "renews_at": "2026-01-21T00:00:00Z"},
        now=now,
    ) is None
    assert included_monthly_usage_from_documents(
        usage,
        {"Plan": "pro", "renews_at": "2026-01-21T00:00:00Z"},
        now=now,
    ) is None
    assert included_monthly_usage_from_documents(
        {"extra_usage": {"remaining": 8}},
        {"Plan": "pro", "renews_at": "2026-01-21T00:00:00Z"},
        now=now,
    ) is None


def test_does_not_treat_key_cap_or_key_usage_as_account_credit_remaining():
    assert account_credit_remaining_from_credits_payload(
        {"data": {"limit": 100, "limit_remaining": 74.5, "usage": 25.5}}
    ) is None
    assert account_credit_remaining_from_credits_payload(
        {"data": {"total_credits": 10}}
    ) is None
    assert account_credit_remaining_from_credits_payload(
        {"total_credits": 10, "total_usage": 1}
    ) is None


def test_maps_account_credit_remaining_including_zero_and_negative():
    assert account_credit_remaining_from_credits_payload(
        {"data": {"total_credits": 10, "total_usage": 1.5}}
    ) == 8.5
    assert account_credit_remaining_from_credits_payload(
        {"data": {"total_credits": 10, "total_usage": 10}}
    ) == 0.0
    assert account_credit_remaining_from_credits_payload(
        {"data": {"total_credits": 10, "total_usage": 10.5}}
    ) == -0.5


def test_reset_phrase_uses_day_and_week_cutoffs():
    usage = {
        "from": "2026-09-01T00:00:00Z",
        "buckets": [{"from": "2026-10-01T00:00:00Z", "usage_usd": 1}],
    }
    account = {"Plan": "team", "renews_at": "2026-01-15T00:00:00Z"}
    six_days = included_monthly_usage_from_documents(
        usage,
        account,
        now=datetime(2026, 10, 8, 21, 0, tzinfo=timezone.utc),
    )
    assert six_days["resets"] == "Resets in 6 days."
    one_week = included_monthly_usage_from_documents(
        usage,
        account,
        now=datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc),
    )
    assert one_week["resets"] == "Resets in 1 week."
    assert one_week["summary"] == "$1 of $1000 used"
