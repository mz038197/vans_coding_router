"""OAuth Client registry and signing key at startup (ADR 0094)."""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

from src.bootstrap import build_container
from src.infrastructure.auth.oauth_signing import load_oauth_signing_key
from src.infrastructure.config import load_router_settings

SECRET_HASH = hashlib.sha256(b"agent-secret").hexdigest()


def _pem(private_key) -> str:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


RSA_PEM = _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))


def _config(tmp_path, *, public_url="http://127.0.0.1:8000", oauth: list[str] | None = None) -> str:
    lines = [
        f'public_url: "{public_url}"',
        "auth:",
        "  dev_auth_enabled: true" if "127.0.0.1" in public_url else "  dev_auth_enabled: false",
        '  google_client_id: "gid"',
        '  google_client_secret: "gsecret"',
        "database:",
        f'  path: "{(tmp_path / "router.db").as_posix()}"',
        f'  archive_dir: "{(tmp_path / "archive").as_posix()}"',
    ]
    config = tmp_path / "router.yaml"
    config.write_text("\n".join(lines + (oauth or [])), encoding="utf-8")
    return str(config)


CLIENTS = [
    "oauth:",
    "  clients:",
    "    agent-builder:",
    '      name: "MiTAC Agent Builder"',
    "      redirect_uris:",
    '        - "https://agent.example/oauth/callback"',
    "      scopes: [classroom]",
    f'      client_secret_sha256: "{SECRET_HASH}"',
    "    club-booking-admin:",
    "      redirect_uris:",
    '        - "https://booking.example/auth/callback"',
    '      scopes: "openid teacher"',
]


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in ("VCR_SERVICE_TOKENS", "FLY_APP_NAME", "DATABASE_URL", "PUBLIC_URL", "VCR_OAUTH_SIGNING_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_clients_load_from_router_yaml(tmp_path):
    settings = load_router_settings(_config(tmp_path, oauth=CLIENTS))

    agent = settings.oauth.clients["agent-builder"]
    booking = settings.oauth.clients["club-booking-admin"]
    assert agent.redirect_uris == ("https://agent.example/oauth/callback",)
    assert agent.scopes == ("classroom",)
    assert agent.has_secret and agent.client_secret_sha256 == SECRET_HASH
    assert agent.name == "MiTAC Agent Builder"
    assert booking.scopes == ("openid", "teacher")
    assert not booking.has_secret


def test_example_config_registers_agent_builder_and_club_booking():
    clients = load_router_settings("config/router.example.yaml").oauth.clients

    assert clients["agent-builder"].scopes == ("classroom",)
    assert clients["agent-builder"].client_secret_env == "VCR_OAUTH_AGENT_BUILDER_SECRET"
    assert clients["club-booking-admin"].scopes == ("openid", "teacher")
    assert clients["club-booking-admin"].redirect_uris == ("http://localhost:3000/auth/callback",)
    # Production registers the club-booking teacher admin only; agent-builder waits
    # for MiTAC to replace its localhost callback.
    prod = load_router_settings("config/router.prod.yaml").oauth.clients
    assert set(prod) == {"club-booking-admin"}
    assert prod["club-booking-admin"].redirect_uris == ("https://club-booking-board.vercel.app/auth/callback",)
    assert prod["club-booking-admin"].scopes == ("openid", "teacher")


@pytest.mark.parametrize(
    "client_lines",
    [
        ["    x:", "      scopes: [classroom]"],
        ["    x:", "      redirect_uris: []", "      scopes: [classroom]"],
        ["    x:", '      redirect_uris: ["https://a.example/cb"]'],
        ["    x:", '      redirect_uris: ["https://a.example/cb"]', "      scopes: [classroom]", '      client_secret_sha256: "abc"'],
        [
            "    x:",
            '      redirect_uris: ["https://a.example/cb"]',
            "      scopes: [classroom]",
            f'      client_secret_sha256: "{SECRET_HASH}"',
            "      client_secret_env: X_SECRET",
        ],
    ],
)
def test_malformed_client_registration_refuses_to_start(tmp_path, client_lines):
    with pytest.raises(ValueError, match="oauth.clients"):
        load_router_settings(_config(tmp_path, oauth=["oauth:", "  clients:", *client_lines]))


def test_local_development_serves_with_a_development_key(tmp_path):
    container = build_container(request_timeout=1.0, config_path=_config(tmp_path, oauth=CLIENTS))

    assert container.oauth_use_case is not None
    assert container.oauth_use_case.jwks()["keys"][0]["alg"] == "RS256"


def test_production_with_clients_and_no_signing_key_refuses_to_start(tmp_path, monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "vans-coding-router")
    monkeypatch.setenv("VCR_SERVICE_TOKENS", '{"%s": "road-test"}' % SECRET_HASH)

    with pytest.raises(ValueError, match="VCR_OAUTH_SIGNING_KEY"):
        build_container(
            request_timeout=1.0,
            config_path=_config(tmp_path, public_url="https://router.example", oauth=CLIENTS),
        )


def test_public_url_with_clients_and_no_signing_key_refuses_to_start(tmp_path):
    with pytest.raises(ValueError, match="VCR_OAUTH_SIGNING_KEY"):
        build_container(
            request_timeout=1.0,
            config_path=_config(tmp_path, public_url="https://router.example", oauth=CLIENTS),
        )


def test_production_without_clients_starts_with_the_authorization_server_off(tmp_path, monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "vans-coding-router")
    monkeypatch.setenv("VCR_SERVICE_TOKENS", '{"%s": "road-test"}' % SECRET_HASH)

    container = build_container(
        request_timeout=1.0, config_path=_config(tmp_path, public_url="https://router.example")
    )

    assert container.oauth_use_case is None


def test_production_serves_with_the_configured_signing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "vans-coding-router")
    monkeypatch.setenv("VCR_SERVICE_TOKENS", '{"%s": "road-test"}' % SECRET_HASH)
    monkeypatch.setenv("VCR_OAUTH_SIGNING_KEY", RSA_PEM)

    container = build_container(
        request_timeout=1.0,
        config_path=_config(tmp_path, public_url="https://router.example", oauth=CLIENTS),
    )

    assert container.oauth_use_case.jwks() == load_oauth_signing_key(RSA_PEM).jwks()
    assert container.oauth_use_case.discovery()["issuer"] == "https://router.example"


@pytest.mark.parametrize("raw", ["not a key", base64.b64encode(b"not a key").decode()])
def test_malformed_signing_key_refuses_to_start(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("VCR_OAUTH_SIGNING_KEY", raw)

    with pytest.raises(ValueError, match="VCR_OAUTH_SIGNING_KEY"):
        build_container(request_timeout=1.0, config_path=_config(tmp_path, oauth=CLIENTS))


def test_signing_key_may_be_base64_pem():
    encoded = base64.b64encode(RSA_PEM.encode("ascii")).decode("ascii")

    assert load_oauth_signing_key(encoded).jwks() == load_oauth_signing_key(RSA_PEM).jwks()


def test_ec_p256_key_signs_es256():
    key = load_oauth_signing_key(_pem(ec.generate_private_key(ec.SECP256R1())))

    (jwk,) = key.jwks()["keys"]
    assert key.alg == "ES256"
    assert jwk["kty"] == "EC" and jwk["crv"] == "P-256" and "d" not in jwk
    assert len(key.sign_jwt({"sub": "1"}).split(".")[2]) == 86  # 64-byte r||s, base64url


def test_app_serves_discovery_when_the_container_has_the_authorization_server(tmp_path):
    from fastapi import FastAPI

    from src.presentation.fastapi.routers.oauth_router import create_oauth_router

    container = build_container(request_timeout=1.0, config_path=_config(tmp_path, oauth=CLIENTS))
    app = FastAPI()
    app.include_router(create_oauth_router(container.oauth_use_case, container.router_settings))

    response = TestClient(app).get("/.well-known/openid-configuration")

    assert response.json()["issuer"] == "http://127.0.0.1:8000"
