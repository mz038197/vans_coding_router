import json

from src.presentation.fastapi.openai_errors import (
    is_chat_completions_path,
    is_openai_compatible_path,
    is_responses_path,
    make_openai_error_body,
    openai_stream_error_bytes,
)


def test_is_openai_compatible_path():
    assert is_chat_completions_path("/v1/chat/completions")
    assert is_responses_path("/v1/responses")
    assert is_openai_compatible_path("/v1/chat/completions")
    assert is_openai_compatible_path("/v1/responses")
    assert not is_openai_compatible_path("/v1/models")


def test_make_openai_error_body_shape():
    body = make_openai_error_body("failed", error_type="server_error", code="x")
    assert body == {
        "error": {
            "message": "failed",
            "type": "server_error",
            "param": None,
            "code": "x",
        }
    }


def test_openai_stream_error_bytes_is_valid_json():
    raw = openai_stream_error_bytes("upstream down", error_type="server_error")
    line = raw.decode("utf-8").strip()
    assert line.startswith("data: ")
    payload = json.loads(line[6:])
    assert payload["error"]["message"] == "upstream down"
