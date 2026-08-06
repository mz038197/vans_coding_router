from src.domain.extra_usage import is_extra_usage_exhaustion


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
