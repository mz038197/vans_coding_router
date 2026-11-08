"""The Key Check rate limit is a setting (ADR 0076): 600 calls a minute per Partner Service unless the config says otherwise."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.bootstrap import build_container
from src.infrastructure.config import apply_runtime_settings, load_router_settings
from src.presentation.fastapi.routers.key_check_router import create_key_check_router

CREDENTIAL = "road-test-credential"


def _config(tmp_path: Path, *extra_lines: str) -> str:
    config = tmp_path / "router.yaml"
    config.write_text(
        "\n".join(
            [
                'public_url: "http://127.0.0.1:8000"',
                "database:",
                f'  path: "{(tmp_path / "router.db").as_posix()}"',
                f'  archive_dir: "{(tmp_path / "archive").as_posix()}"',
                *extra_lines,
            ]
        ),
        encoding="utf-8",
    )
    return str(config)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    monkeypatch.setenv("VCR_SERVICE_TOKENS", json.dumps({hashlib.sha256(CREDENTIAL.encode()).hexdigest(): "road-test"}))
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_URL", raising=False)


def test_the_limit_defaults_to_600_calls_a_minute(tmp_path):
    settings = load_router_settings(_config(tmp_path))

    assert settings.key_check.calls_per_minute_per_service == 600


def test_the_configured_limit_survives_runtime_settings(tmp_path):
    settings = load_router_settings(_config(tmp_path, "key_check:", "  calls_per_minute_per_service: 1200"))

    assert settings.key_check.calls_per_minute_per_service == 1200
    overridden = apply_runtime_settings(settings, {"student_default_ttl_hours": "3"})
    assert overridden.key_check.calls_per_minute_per_service == 1200


def _started_app_caller(config_path: str):
    container = build_container(request_timeout=1.0, config_path=config_path)
    app = FastAPI()
    app.include_router(
        create_key_check_router(
            container.key_check_use_case,
            container.service_tokens,
            rate_limiter=container.key_check_rate_limiter,
        )
    )
    client = TestClient(app)

    def call():
        return client.post(
            "/internal/key-check",
            json={"api_key": "vcr_sk_unknown"},
            headers={"Authorization": f"Bearer {CREDENTIAL}"},
        )

    return call


def test_the_started_app_limits_key_check_to_the_configured_number(tmp_path):
    call = _started_app_caller(_config(tmp_path, "key_check:", "  calls_per_minute_per_service: 2"))

    assert [call().status_code for _ in range(3)] == [200, 200, 429]


def test_the_started_app_with_no_setting_answers_the_601st_call_in_a_minute_with_429(tmp_path):
    call = _started_app_caller(_config(tmp_path))

    answers = [call().status_code for _ in range(600)]
    over = call()

    assert answers == [200] * 600
    assert over.status_code == 429
    assert "vcr_sk_unknown" not in over.text


@pytest.mark.parametrize("value", ["0", "-5", "many", "1.5"])
def test_a_limit_that_is_not_a_positive_whole_number_refuses_to_start(tmp_path, value):
    with pytest.raises(ValueError, match="calls_per_minute_per_service"):
        load_router_settings(_config(tmp_path, "key_check:", f"  calls_per_minute_per_service: {value}"))
