"""A provider that cannot embed or decide answers with an OpenAI-shaped invalid request error."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.errors import DecisionNotSupportedError, EmbeddingsNotSupportedError
from src.presentation.fastapi.error_handlers import register_error_handlers


@pytest.mark.parametrize(
    ("path", "error", "code"),
    [
        ("/v1/embeddings", EmbeddingsNotSupportedError, "embeddings_not_supported"),
        ("/v1/decisions", DecisionNotSupportedError, "decision_not_supported"),
    ],
)
def test_an_unsupported_capability_is_an_invalid_request(path, error, code):
    app = FastAPI()
    register_error_handlers(app)

    @app.post(path)
    async def refuse():
        raise error()

    response = TestClient(app).post(path, json={})

    assert response.status_code == 400
    body = response.json()["error"]
    assert (body["type"], body["code"]) == ("invalid_request_error", code)
    assert body["message"]
