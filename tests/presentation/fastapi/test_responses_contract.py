from fastapi.testclient import TestClient

from tests.presentation.fastapi.test_api_contract import build_test_client


def test_responses_rejects_missing_api_key(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/responses",
        json={"model": "fake-model", "input": "hello"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_responses_nonstream_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "fake-model",
            "input": "hello",
            "reasoning": {"effort": "low"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "response"
    assert fake_gateway.last_responses_body is not None
    assert fake_gateway.last_responses_body["model"] == "fake-model"
    assert len(fake_logger.entries) == 1
    assert fake_logger.entries[0]["model"] == "fake-model"


def test_responses_rejects_previous_response_id(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "fake-model",
            "input": "hello",
            "previous_response_id": "resp_abc123",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["param"] == "previous_response_id"
    assert payload["error"]["code"] == "previous_response_not_found"
    assert fake_gateway.last_responses_body is None


def test_responses_stream_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    with client.stream(
        "POST",
        "/v1/responses",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "input": "hello", "stream": True},
    ) as response:
        body = b"".join(response.iter_bytes()).decode("utf-8")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "response.created" in body
        assert fake_gateway.last_responses_body is not None
        assert fake_gateway.last_responses_body["stream"] is True
