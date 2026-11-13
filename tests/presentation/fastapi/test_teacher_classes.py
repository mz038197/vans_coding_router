"""Teacher Classes over HTTP: a Partner Service asks which Classes a user may manage (ADR 0094)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.per_minute_rate_limit import PerMinuteRateLimiter
from src.application.use_cases.key_check_use_case import KeyCheckUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.key_check_router import create_key_check_router

CREDENTIAL = "club-booking-board-credential-0123456789"
CONTRACT_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "teacher-classes"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _example(name: str):
    return json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))


def _client(tmp_path):
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-session-secret",
            dev_auth_enabled=True,
        ),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    app.include_router(
        create_key_check_router(
            KeyCheckUseCase(repo),
            {_sha256(CREDENTIAL): "club-booking-board"},
            PerMinuteRateLimiter(1000),
        )
    )
    return TestClient(app), repo


def _ask(client, body, credential=CREDENTIAL):
    headers = {"Authorization": f"Bearer {credential}"} if credential is not None else {}
    return client.post("/internal/teacher-classes", json=body, headers=headers)


def _teacher_with_classes(repo, email="teacher@school.edu", names=("Mon AM", "Wed PM")):
    teacher = repo.upsert_google_user(email, "Teacher")
    classes = [repo.create_class(teacher["id"], name, None) for name in names]
    return teacher, classes


def test_teacher_is_answered_with_the_classes_they_own(tmp_path):
    client, repo = _client(tmp_path)
    teacher, classes = _teacher_with_classes(repo)
    _teacher_with_classes(repo, email="other@school.edu", names=("Someone else's",))

    response = _ask(client, {"user_id": teacher["id"]})

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "user_id": teacher["id"],
        "is_admin": False,
        "classes": [
            {"id": classes[0]["id"], "name": "Mon AM"},
            {"id": classes[1]["id"], "name": "Wed PM"},
        ],
    }


def test_admin_is_answered_with_every_class_including_ended_ones(tmp_path):
    client, repo = _client(tmp_path)
    _, classes = _teacher_with_classes(repo)
    repo.set_class_status(classes[0]["id"], "ended")
    admin = repo.upsert_google_user("admin@school.edu", "Admin")

    answer = _ask(client, {"user_id": admin["id"]}).json()

    assert answer["accepted"] is True
    assert answer["is_admin"] is True
    assert answer["classes"] == [
        {"id": classes[0]["id"], "name": "Mon AM"},
        {"id": classes[1]["id"], "name": "Wed PM"},
    ]


def test_teacher_who_owns_no_class_is_accepted_with_no_classes(tmp_path):
    client, repo = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")

    assert _ask(client, {"user_id": teacher["id"]}).json() == {
        "accepted": True,
        "user_id": teacher["id"],
        "is_admin": False,
        "classes": [],
    }


def test_student_is_refused(tmp_path):
    client, repo = _client(tmp_path)
    student = repo.upsert_google_user("student@gmail.com", "Student")

    assert _ask(client, {"user_id": student["id"]}).json() == _example("refused.json")


def test_unknown_user_is_refused(tmp_path):
    client, _ = _client(tmp_path)

    assert _ask(client, {"user_id": 99999}).json() == _example("refused.json")


def test_disabled_teacher_is_refused(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    repo.update_user(teacher["id"], status="inactive")

    assert _ask(client, {"user_id": teacher["id"]}).json() == _example("refused.json")


def test_legacy_teacher_role_with_no_role_rows_is_refused(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    with repo._connect() as conn:  # a legacy users.role and no user_roles rows (ADR 0078)
        conn.execute("UPDATE users SET role = 'teacher' WHERE id = ?", (teacher["id"],))
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (teacher["id"],))

    assert _ask(client, {"user_id": teacher["id"]}).json() == _example("refused.json")


@pytest.mark.parametrize(
    "header",
    [None, "Bearer wrong-credential", f"Basic {CREDENTIAL}", "Bearer ", CREDENTIAL],
)
def test_missing_or_wrong_service_credential_gets_the_key_check_401(tmp_path, header):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    headers = {"Authorization": header} if header is not None else {}

    response = client.post("/internal/teacher-classes", json={"user_id": teacher["id"]}, headers=headers)
    key_check = client.post("/internal/key-check", json={"api_key": "vcr_sk_x"}, headers=headers)

    assert response.status_code == 401
    assert response.json() == key_check.json() == _example("unauthorized.json")


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b"{}", b'{"user_id": "42"}', b'{"user_id": true}', b'{"user_id": 4.2}', b"\xff"],
)
def test_unreadable_body_gets_a_fixed_400(tmp_path, body):
    client, _ = _client(tmp_path)

    response = client.post(
        "/internal/teacher-classes",
        content=body,
        headers={"Authorization": f"Bearer {CREDENTIAL}", "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == _example("bad-request.json")


def _shape(value):
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shape(item) for item in value[:1]]
    return type(value).__name__


def test_accepted_answer_matches_the_contract_example(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)

    answer = _ask(client, {"user_id": teacher["id"]}).json()

    assert _shape(answer) == _shape(_example("accepted.json"))
