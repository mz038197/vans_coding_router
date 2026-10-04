import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.errors import AuthenticationError, ServiceUnavailableError, UpstreamServiceError
from src.presentation.fastapi.error_handlers import register_error_handlers


def _error_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_unexpected_exception_on_an_openai_path_returns_a_fixed_sentence_and_one_error(caplog):
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/v1/chat/completions")
    async def boom():
        raise RuntimeError("secret boom")

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions?token=secret", json={})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "message": "Internal server error",
            "type": "server_error",
            "param": None,
            "code": None,
        }
    }
    assert "secret boom" not in response.text
    records = _error_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert message == "POST /v1/chat/completions -> 500: Internal server error"
    assert "token=secret" not in message
    assert "secret boom" not in message
    assert records[0].exc_info is not None
    assert records[0].exc_info[0] is RuntimeError


def test_unexpected_exception_on_a_non_openai_path_uses_detail(caplog):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/v1/models")
    async def boom():
        raise RuntimeError("secret boom")

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.get("/v1/models")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    records = _error_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "GET /v1/models -> 500: Internal server error"


def test_service_unavailable_returned_to_the_student_emits_one_error(caplog):
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/v1/chat/completions")
    async def unavailable():
        raise ServiceUnavailableError("ollama_cloud unavailable: connection refused")

    client = TestClient(app)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "ollama_cloud unavailable: connection refused"
    records = _error_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == (
        "POST /v1/chat/completions -> 503: ollama_cloud unavailable: connection refused"
    )
    assert "backend=" not in records[0].getMessage()
    assert records[0].exc_info[0] is ServiceUnavailableError


def test_an_expired_style_auth_failure_emits_no_error(caplog):
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/v1/chat/completions")
    async def denied():
        raise AuthenticationError()

    client = TestClient(app)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions")

    assert response.status_code == 401
    assert _error_records(caplog) == []


def test_upstream_authentication_failure_names_the_upstream_status_and_provider(caplog):
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/v1/chat/completions")
    async def rejected():
        raise UpstreamServiceError(
            status_code=401,
            backend="openrouter",
            body={"error": {"message": "Invalid API key sk-secret"}},
        )

    client = TestClient(app)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions")

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Upstream provider authentication failed. Contact your teacher or administrator."
    )
    assert "sk-secret" not in response.text
    records = _error_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert message == (
        "POST /v1/chat/completions -> 401 backend=openrouter: "
        "Upstream provider authentication failed. Contact your teacher or administrator."
    )
    assert "sk-secret" not in message
    assert records[0].exc_info[0] is UpstreamServiceError


def test_an_ordinary_upstream_refusal_emits_no_error(caplog):
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/v1/chat/completions")
    async def refused():
        raise UpstreamServiceError(
            status_code=400,
            backend="openrouter",
            body={"error": {"message": "bad prompt"}},
        )

    client = TestClient(app)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions")

    assert response.status_code == 400
    assert _error_records(caplog) == []


def test_extra_usage_exhaustion_returned_to_the_student_emits_one_error(caplog):
    app = FastAPI()
    register_error_handlers(app)
    sentence = "extra usage balance is empty, add extra usage"

    @app.post("/v1/chat/completions")
    async def exhausted():
        raise UpstreamServiceError(
            status_code=402,
            backend="ollama_cloud",
            body={"error": sentence},
        )

    client = TestClient(app)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions")

    assert response.status_code == 402
    assert response.json()["error"]["message"] == sentence
    records = _error_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == f"POST /v1/chat/completions -> 402 backend=ollama_cloud: {sentence}"


def test_a_402_that_is_not_exhaustion_emits_no_error(caplog):
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/v1/chat/completions")
    async def other_402():
        raise UpstreamServiceError(
            status_code=402,
            backend="openrouter",
            body={"error": {"message": "payment required for another reason"}},
        )

    client = TestClient(app)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions")

    assert response.status_code == 402
    assert _error_records(caplog) == []


def test_credit_exhaustion_returned_to_the_student_emits_one_error(caplog):
    app = FastAPI()
    register_error_handlers(app)
    sentence = "Insufficient credits. Add more using https://openrouter.ai/credits"

    @app.post("/v1/chat/completions")
    async def exhausted():
        raise UpstreamServiceError(
            status_code=402,
            backend="openrouter",
            body={"error": {"message": sentence, "metadata": {"error_type": "payment_required"}}},
        )

    client = TestClient(app)
    with caplog.at_level(logging.ERROR, logger="src"):
        response = client.post("/v1/chat/completions")

    assert response.status_code == 402
    assert response.json()["error"]["message"] == sentence
    records = _error_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == f"POST /v1/chat/completions -> 402 backend=openrouter: {sentence}"
