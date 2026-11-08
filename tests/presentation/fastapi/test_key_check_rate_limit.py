"""Key Check is limited per Partner Service (ADR 0076): over the limit is 429 and one ERROR Signal."""

from __future__ import annotations

import hashlib
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.per_minute_rate_limit import PerMinuteRateLimiter
from src.application.use_cases.key_check_use_case import KeyCheckUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.key_check_router import create_key_check_router

MCP_CREDENTIAL = "mcp-credential-0123456789abcdef"
ROAD_TEST_CREDENTIAL = "road-test-credential-fedcba9876543210"
UNKNOWN_KEY = "vcr_sk_" + "c" * 64


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client(tmp_path, rate_limiter=None):
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-session-secret", dev_auth_enabled=True),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    service_tokens = {
        _sha256(MCP_CREDENTIAL): "vans-mcp-server",
        _sha256(ROAD_TEST_CREDENTIAL): "road-test",
    }
    app = FastAPI()
    app.include_router(create_key_check_router(KeyCheckUseCase(repo), service_tokens, rate_limiter=rate_limiter))
    return TestClient(app)


def _key_check(client, credential=MCP_CREDENTIAL):
    return client.post(
        "/internal/key-check",
        json={"api_key": UNKNOWN_KEY},
        headers={"Authorization": f"Bearer {credential}"},
    )


def _limited(tmp_path, limit=3):
    clock = FakeClock()
    return _client(tmp_path, PerMinuteRateLimiter(limit, clock=clock)), clock


def _error_records(caplog):
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_the_601st_call_in_a_minute_gets_429_by_default(tmp_path):
    client = _client(tmp_path)

    answers = [_key_check(client).status_code for _ in range(600)]
    over = _key_check(client)

    assert answers == [200] * 600
    assert over.status_code == 429
    assert UNKNOWN_KEY not in over.text


def test_one_partner_service_over_its_limit_leaves_the_others_their_own(tmp_path):
    client, _ = _limited(tmp_path, limit=3)
    for _ in range(3):
        _key_check(client)

    assert _key_check(client).status_code == 429
    assert [_key_check(client, ROAD_TEST_CREDENTIAL).status_code for _ in range(3)] == [200] * 3
    assert _key_check(client, ROAD_TEST_CREDENTIAL).status_code == 429


def test_the_limit_frees_up_a_minute_after_the_calls(tmp_path):
    client, clock = _limited(tmp_path, limit=3)
    for _ in range(3):
        _key_check(client)
    clock.now += 59

    assert _key_check(client).status_code == 429

    clock.now += 1
    assert _key_check(client).status_code == 200


def test_going_over_the_limit_sends_one_error_naming_only_the_service(tmp_path, caplog):
    client, _ = _limited(tmp_path, limit=3)
    with caplog.at_level(logging.ERROR, logger="src"):
        for _ in range(3):
            _key_check(client)
        assert _error_records(caplog) == []

        _key_check(client)

    records = _error_records(caplog)
    assert len(records) == 1
    assert records[0].name.startswith("src.")
    message = records[0].getMessage()
    assert "vans-mcp-server" in message
    assert "road-test" not in message
    assert UNKNOWN_KEY not in message
    assert MCP_CREDENTIAL not in message
    assert records[0].exc_info is None


def test_further_refused_calls_in_the_same_overrun_send_no_more_errors(tmp_path, caplog):
    client, clock = _limited(tmp_path, limit=3)
    with caplog.at_level(logging.ERROR, logger="src"):
        for _ in range(3):
            _key_check(client)
        for _ in range(5):
            _key_check(client)
        assert len(_error_records(caplog)) == 1

        clock.now += 60
        for _ in range(4):
            _key_check(client)

    assert len(_error_records(caplog)) == 2
