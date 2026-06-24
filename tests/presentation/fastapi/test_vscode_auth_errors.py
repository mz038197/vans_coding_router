from api_test_utils import build_test_client
from src.domain.errors import UpstreamServiceError
from src.infrastructure.auth.client_api_key import classify_client_api_key


def test_classify_client_api_key():
    assert classify_client_api_key("") == "missing"
    assert classify_client_api_key("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def") == "copilot_token"
    assert classify_client_api_key("valid-key") is None
    assert classify_client_api_key("vcr_sk_abc123") is None


def test_auth_check_valid_key(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.get("/v1/auth/check", headers={"Authorization": "Bearer valid-key"})
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_auth_check_invalid_key(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.get("/v1/auth/check", headers={"Authorization": "Bearer bad-key"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_responses_rejects_copilot_jwt_as_bearer(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"},
        json={"model": "fake-model", "input": "hello"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "wrong_credential_type"


async def _raise_upstream_auth_error(_body):
    raise UpstreamServiceError(status_code=403, backend="ollama_cloud", body="forbidden")


def test_upstream_auth_failure_returns_502_not_403(fake_repo, fake_gateway, fake_logger):
    fake_gateway.responses_create = _raise_upstream_auth_error  # type: ignore[method-assign]
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "input": "hello"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_authentication_error"
