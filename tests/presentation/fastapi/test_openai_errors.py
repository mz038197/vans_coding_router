import json

from src.presentation.fastapi.openai_errors import (
    IMAGES_PATH,
    IMAGES_MODELS_PATH,
    is_chat_completions_path,
    is_openai_compatible_path,
    is_responses_path,
    make_openai_error_body,
    openai_stream_chat_error_bytes,
    openai_stream_error_bytes,
)


def test_is_openai_compatible_path():
    assert is_chat_completions_path("/v1/chat/completions")
    assert is_responses_path("/v1/responses")
    assert is_openai_compatible_path("/v1/chat/completions")
    assert is_openai_compatible_path("/v1/responses")
    assert is_openai_compatible_path(IMAGES_PATH)
    assert is_openai_compatible_path(IMAGES_MODELS_PATH)
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


def test_openai_stream_chat_error_bytes_includes_choices():
    raw = openai_stream_chat_error_bytes("upstream down", model="m")
    text = raw.decode("utf-8")
    assert "choices" in text
    assert "upstream down" in text
    assert "data: [DONE]" in text
    assert '"error"' not in text
