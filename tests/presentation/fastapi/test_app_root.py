from fastapi.testclient import TestClient

from app import app


def test_root_redirects_to_portal():
    client = TestClient(app)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/portal"
