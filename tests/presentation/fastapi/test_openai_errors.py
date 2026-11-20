import json

from src.presentation.fastapi.openai_errors import (
    AUDIO_TRANSCRIPTIONS_PATH,
    IMAGES_PATH,
    IMAGES_MODELS_PATH,
    is_chat_completions_path,
    is_openai_compatible_path,
    is_responses_path,
    make_openai_error_body,
    openai_stream_chat_error_bytes,
    openai_stream_error_bytes,
    openai_stream_responses_error_bytes,
)


def test_is_openai_compatible_path():
    assert is_chat_completions_path("/v1/chat/completions")
    assert is_responses_path("/v1/responses")
    assert is_openai_compatible_path("/v1/chat/completions")
    assert is_openai_compatible_path("/v1/responses")
    assert is_openai_compatible_path(IMAGES_PATH)
    assert is_openai_compatible_path(IMAGES_MODELS_PATH)
    assert is_openai_compatible_path(AUDIO_TRANSCRIPTIONS_PATH)
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


def test_openai_stream_responses_error_bytes_completes_with_text():
    raw = openai_stream_responses_error_bytes("extra usage empty", model="kimi-k3:cloud")
    text = raw.decode("utf-8")
    assert "response.completed" in text
    assert "extra usage empty" in text
    assert "output_text" in text


def _dict_keyed_body_client():
    """A route whose body has a caller-keyed dict, shaped like a Decision's questions."""
    from typing import Literal

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import BaseModel

    from src.presentation.fastapi.error_handlers import register_error_handlers

    class Question(BaseModel):
        type: Literal["noul"]
        instructions: str

    class DictKeyedBody(BaseModel):
        model: str
        questions: dict[str, Question]
        notes: list[Question] | None = None

    app = FastAPI()
    register_error_handlers(app)

    @app.post("/v1/decisions")
    async def decisions(body: DictKeyedBody):
        return {}

    return TestClient(app)


def test_malformed_body_param_stops_before_a_caller_supplied_dict_key():
    client = _dict_keyed_body_client()

    response = client.post(
        "/v1/decisions",
        json={"model": "m", "questions": {"學生秘密題目": {"type": "noul"}}},
    )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "questions"
    assert "學生秘密題目" not in response.text


def test_malformed_body_param_keeps_schema_fields_and_list_indices():
    client = _dict_keyed_body_client()

    response = client.post(
        "/v1/decisions",
        json={"model": "m", "questions": {}, "notes": [{"type": "noul", "instructions": "x"}, {"type": "noul"}]},
    )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "notes[1].instructions"
