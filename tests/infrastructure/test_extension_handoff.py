"""Sign-in Handoff: short-lived, single-use proof for extension redeem."""

from __future__ import annotations

import time

import pytest

from src.infrastructure.auth.extension_handoff import ExtensionHandoffService


def test_create_and_consume_returns_user_id():
    service = ExtensionHandoffService(session_secret="secret", max_age_seconds=600)
    token = service.create_token(user_id=42)
    assert service.consume_token(token) == 42


def test_consume_rejects_tampered_token():
    service = ExtensionHandoffService(session_secret="secret", max_age_seconds=600)
    token = service.create_token(user_id=42)
    tampered = token[:-4] + "dead"
    with pytest.raises(ValueError, match="invalid"):
        service.consume_token(tampered)


def test_consume_rejects_expired_token():
    service = ExtensionHandoffService(session_secret="secret", max_age_seconds=60)
    token = service.create_token(user_id=7)
    with pytest.raises(ValueError, match="expired"):
        with _shift_time(service, delta_seconds=120):
            service.consume_token(token)


def test_consume_rejects_second_use_when_nonce_marked():
    used: set[str] = set()

    def mark_used(nonce: str) -> bool:
        if nonce in used:
            return False
        used.add(nonce)
        return True

    service = ExtensionHandoffService(
        session_secret="secret",
        max_age_seconds=600,
        try_mark_nonce_used=mark_used,
    )
    token = service.create_token(user_id=3)
    assert service.consume_token(token) == 3
    with pytest.raises(ValueError, match="used"):
        service.consume_token(token)


class _shift_time:
    def __init__(self, service: ExtensionHandoffService, delta_seconds: int):
        self._service = service
        self._delta = delta_seconds
        self._orig = service._now

    def __enter__(self):
        base = self._orig()
        self._service._now = lambda: base + self._delta
        return self

    def __exit__(self, *args):
        self._service._now = self._orig
