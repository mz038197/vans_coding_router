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


def test_rejects_402_without_extra_usage_text():
    assert is_extra_usage_exhaustion(402, {"error": "payment required"}) is False


def test_rejects_non_402_even_with_extra_usage_text():
    body = {"error": "extra usage balance is empty"}
    assert is_extra_usage_exhaustion(429, body) is False
    assert is_extra_usage_exhaustion(500, body) is False


def test_accepts_json_string_body():
    raw = '{"error":"extra usage balance is empty, add extra usage"}'
    assert is_extra_usage_exhaustion(402, raw) is True
