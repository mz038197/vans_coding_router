import pytest

from presentation.fastapi.test_decisions_contract import _sqlite_api_client, _student_key

_PATHS = ["/v1/decisions", "/v1/responses", "/v1/embeddings"]
_UNREADABLE_BODIES = [
    b'{"model":"vcr-auto","state":{"prompt":"\xb0\xfa"}}',
    b'{"model":"vcr-auto",',
    b'["vcr-auto"]',
]


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize("body", _UNREADABLE_BODIES)
def test_unreadable_json_body_is_a_400_before_upstream(tmp_path, caplog, path, body):
    client, repo, gateway, _logger = _sqlite_api_client(tmp_path)
    _klass, _session, student_key = _student_key(repo)

    response = client.post(
        path,
        headers={"Authorization": f"Bearer {student_key}", "Content-Type": "application/json"},
        content=body,
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert error["code"] == "invalid_json_body"
    assert gateway.last_decision_body is None
    assert not [record for record in caplog.records if record.levelname == "ERROR"]
