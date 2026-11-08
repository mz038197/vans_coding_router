from fastapi.testclient import TestClient

from app import app


def test_root_redirects_to_portal():
    client = TestClient(app)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/portal"


def test_key_check_is_mounted_and_refuses_a_call_without_a_service_credential():
    client = TestClient(app)
    response = client.post("/internal/key-check", json={"api_key": "vcr_sk_x"})
    assert response.status_code == 401
