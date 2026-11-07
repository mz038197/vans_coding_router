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


def test_extract_unwraps_a_provider_error_wrapped_in_an_http_status_string():
    body = {
        "error": 'HTTP 400: {"detail":{"error_type":"api_usage_error","message":"Invalid image dimensions."}}'
    }
    assert extract_upstream_error_text(body) == "Invalid image dimensions."


def test_extract_reads_each_validation_detail_with_its_location():
    body = {
        "error": (
            'HTTP 422: {"detail":[{"type":"too_short","loc":["body","questions","q","choice","criteria"],'
            '"msg":"Dictionary should have at least 1 item after validation, not 0","input":{}}]}'
        )
    }
    assert extract_upstream_error_text(body) == (
        "body.questions.q.choice.criteria: Dictionary should have at least 1 item after validation, not 0"
    )


def test_extract_reads_a_validation_list_inside_the_message():
    message = (
        '[{"code":"invalid_union","errors":[],"discriminator":"type",'
        '"path":["questions","q","type"],'
        '"message":"Invalid discriminator value. Expected \'noul\' | \'choice\' | \'score\' | \'box\'"}]'
    )
    body = {"error": {"message": message, "code": 400}}
    assert extract_upstream_error_text(body) == (
        "questions.q.type: Invalid discriminator value. Expected 'noul' | 'choice' | 'score' | 'box'"
    )


def test_extract_keeps_an_http_status_string_that_wraps_plain_text():
    assert extract_upstream_error_text({"error": "HTTP 503: upstream down"}) == "HTTP 503: upstream down"


def test_extract_keeps_a_json_string_it_cannot_read():
    assert extract_upstream_error_text({"error": '{"reason":"unknown"}'}) == '{"reason":"unknown"}'
