from src.domain.errors import UpstreamServiceError, extract_upstream_error_text


def test_extract_ollama_string_error():
    body = {
        "error": (
            "this model uses extra usage only (not included plan usage) "
            "and your extra usage balance is empty"
        )
    }
    assert "extra usage balance is empty" in (extract_upstream_error_text(body) or "")


def test_extract_openai_object_error():
    body = {"error": {"message": "model overloaded", "type": "server_error"}}
    assert extract_upstream_error_text(body) == "model overloaded"


def test_extract_json_string_body():
    raw = '{"error":"quota exceeded"}'
    assert extract_upstream_error_text(raw) == "quota exceeded"


def test_extract_plain_text_body():
    assert extract_upstream_error_text("plain upstream failure") == "plain upstream failure"


def test_user_facing_message_prefers_extracted_body():
    exc = UpstreamServiceError(
        status_code=402,
        backend="ollama_cloud",
        body={"error": "extra usage balance is empty, add extra usage"},
    )
    assert "extra usage balance is empty" in exc.user_facing_message()


def test_user_facing_message_masks_auth_errors():
    exc = UpstreamServiceError(status_code=403, backend="ollama_cloud", body="forbidden")
    assert "authentication failed" in exc.user_facing_message().lower()
