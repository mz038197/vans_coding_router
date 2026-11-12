import json

import pytest

from src.domain.extra_usage import is_anthropic_credit_exhaustion


def _error(kind: str, message: str, **extra) -> dict:
    return {"type": "error", "error": {"type": kind, "message": message, **extra}}


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (402, _error("billing_error", "There is a problem with your billing.")),
        (400, _error("invalid_request_error", "You have reached your specified API usage limits. You will regain access on 2026-12-01.")),
        (400, _error("invalid_request_error", "You have reached your specified workspace API usage limits. You will regain access on 2026-12-01.")),
        (
            429,
            _error(
                "rate_limit_error",
                "You have reached your monthly spend limit.",
                details={"error_code": "enforced_spend_limit_reached"},
            ),
        ),
        (400, _error("invalid_request_error", "Your credit balance is too low to access the Anthropic API.")),
        (403, "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing."),
    ],
)
def test_anthropic_credit_exhaustion_signals(status, body):
    assert is_anthropic_credit_exhaustion(status, body) is True
    assert is_anthropic_credit_exhaustion(status, json.dumps(body) if isinstance(body, dict) else body) is True


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (429, _error("rate_limit_error", "Number of request tokens has exceeded your per-minute rate limit")),
        (529, _error("overloaded_error", "Overloaded")),
        (400, _error("invalid_request_error", "messages: field required")),
        (402, _error("invalid_request_error", "not billing")),
        (500, _error("api_error", "Internal server error")),
    ],
)
def test_busy_and_ordinary_errors_are_not_credit_exhaustion(status, body):
    assert is_anthropic_credit_exhaustion(status, body) is False
