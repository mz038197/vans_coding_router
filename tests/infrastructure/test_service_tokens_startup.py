"""`VCR_SERVICE_TOKENS` at startup (ADR 0076): a malformed map refuses to start."""

import hashlib
import json

import pytest

from src.bootstrap import build_container

HASH_A = hashlib.sha256(b"credential-a").hexdigest()
HASH_B = hashlib.sha256(b"credential-b").hexdigest()


def _config(tmp_path) -> str:
    config = tmp_path / "router.yaml"
    config.write_text(
        "\n".join(
            [
                'public_url: "http://127.0.0.1:8000"',
                "auth:",
                "  dev_auth_enabled: true",
                "database:",
                f'  path: "{(tmp_path / "router.db").as_posix()}"',
                f'  archive_dir: "{(tmp_path / "archive").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    return str(config)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    monkeypatch.delenv("VCR_SERVICE_TOKENS", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_URL", raising=False)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '"text"',
        "{}",
        json.dumps({"ABCDEF" + HASH_A[6:]: "road-test"}),
        json.dumps({HASH_A[:-1]: "road-test"}),
        json.dumps({"credential-in-clear": "road-test"}),
        json.dumps({HASH_A: ""}),
        json.dumps({HASH_A: 7}),
        json.dumps({HASH_A: None}),
    ],
)
def test_malformed_service_tokens_refuse_to_start(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("VCR_SERVICE_TOKENS", raw)

    with pytest.raises(ValueError, match="VCR_SERVICE_TOKENS"):
        build_container(request_timeout=1.0, config_path=_config(tmp_path))


def test_one_partner_service_may_be_named_by_two_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("VCR_SERVICE_TOKENS", json.dumps({HASH_A: "road-test", HASH_B: "road-test"}))

    container = build_container(request_timeout=1.0, config_path=_config(tmp_path))

    assert container.service_tokens == {HASH_A: "road-test", HASH_B: "road-test"}


def test_local_development_starts_without_service_tokens(tmp_path):
    container = build_container(request_timeout=1.0, config_path=_config(tmp_path))

    assert container.service_tokens == {}


def test_production_refuses_to_start_without_service_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "vans-coding-router")

    with pytest.raises(ValueError, match="VCR_SERVICE_TOKENS"):
        build_container(request_timeout=1.0, config_path=_config(tmp_path))
