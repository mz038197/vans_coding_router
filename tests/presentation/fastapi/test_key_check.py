"""Key Check over HTTP: a Partner Service asks about one Classroom or Personal API Key (ADR 0077, 0082, 0083)."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.per_minute_rate_limit import PerMinuteRateLimiter
from src.application.use_cases.key_check_use_case import KeyCheckUseCase
from src.infrastructure.auth.service_credentials import load_service_tokens
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.key_check_router import create_key_check_router

MCP_CREDENTIAL = "mcp-credential-0123456789abcdef"
ROAD_TEST_CREDENTIAL = "road-test-credential-fedcba9876543210"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _settings(tmp_path) -> RouterSettings:
    return RouterSettings(
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


def _client(tmp_path, service_tokens=None, clock=None):
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    if service_tokens is None:
        service_tokens = {
            _sha256(MCP_CREDENTIAL): "vans-mcp-server",
            _sha256(ROAD_TEST_CREDENTIAL): "road-test",
        }
    app = FastAPI()
    key_check = KeyCheckUseCase(repo) if clock is None else KeyCheckUseCase(repo, clock=clock)
    app.include_router(create_key_check_router(key_check, service_tokens, PerMinuteRateLimiter(1000)))
    return TestClient(app), repo


def _key_check(client, body, credential=MCP_CREDENTIAL):
    headers = {"Authorization": f"Bearer {credential}"} if credential is not None else {}
    return client.post("/internal/key-check", json=body, headers=headers)


def _live_session(repo, session_at=None):
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1", session_at=session_at)
    return teacher, klass, session


def test_accepted_classroom_api_key_names_student_class_and_class_session(tmp_path):
    client, repo = _client(tmp_path)
    _, klass, session = _live_session(repo)
    redeemed = repo.redeem_invite_with_nickname(session["invite_code"], "Ada")
    student_id = repo.verify_api_key_context(redeemed["api_key"]).user_id

    response = _key_check(client, {"api_key": redeemed["api_key"]})

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "kind": "classroom",
        "student_id": student_id,
        "class_id": klass["id"],
        "class_session_id": session["id"],
    }


def test_admin_holding_a_classroom_api_key_is_answered_as_a_student(tmp_path):
    client, repo = _client(tmp_path)
    _, klass, session = _live_session(repo)
    admin = repo.upsert_google_user("admin@school.edu", "Admin")
    assert "admin" in admin["roles"]
    redeemed = repo.redeem_invite(session["invite_code"], admin["id"])

    response = _key_check(client, {"api_key": redeemed["api_key"]})

    assert response.json() == {
        "accepted": True,
        "kind": "classroom",
        "student_id": admin["id"],
        "class_id": klass["id"],
        "class_session_id": session["id"],
    }


INVALID = {"accepted": False, "reason": "invalid", "message": "無效的 API 金鑰"}
DISABLED = {"accepted": False, "reason": "disabled", "message": "無效的 API 金鑰"}
EXPIRED = {"accepted": False, "reason": "expired", "message": "API 金鑰已過期，請至 Portal 重新取得邀請碼"}
NOT_STARTED = {"accepted": False, "reason": "not_started", "message": "課堂尚未開始，請在開始時間後再使用"}


def test_unknown_key_is_refused_as_invalid(tmp_path):
    client, _ = _client(tmp_path)

    response = _key_check(client, {"api_key": "vcr_sk_" + "0" * 64})

    assert response.status_code == 200
    assert response.json() == INVALID


def _redeemed_key(repo, session_at=None):
    """A student's Classroom API Key. A sitting that has not started is not redeemable, so its key is issued."""
    _, klass, session = _live_session(repo, session_at=session_at)
    student = repo.upsert_google_user("student@gmail.com", "Student")
    if session_at is None:
        api_key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    else:
        api_key = repo.issue_session_key(student["id"], session["id"])
    return api_key, student["id"], klass, session


def test_key_of_a_disabled_student_is_refused_as_disabled(tmp_path):
    client, repo = _client(tmp_path)
    api_key, student_id, _, _ = _redeemed_key(repo)
    repo.update_user(student_id, status="inactive")

    assert _key_check(client, {"api_key": api_key}).json() == DISABLED


def test_disabled_key_is_refused_as_disabled_after_its_student_is_enabled_again(tmp_path):
    client, repo = _client(tmp_path)
    api_key, student_id, _, _ = _redeemed_key(repo)
    repo.update_user(student_id, status="inactive")
    repo.update_user(student_id, status="active")

    assert _key_check(client, {"api_key": api_key}).json() == DISABLED


def test_key_of_an_ended_class_session_is_refused_as_expired(tmp_path):
    client, repo = _client(tmp_path)
    api_key, _, klass, session = _redeemed_key(repo)
    repo.update_class_session(klass["id"], session["id"], status="ended")

    assert _key_check(client, {"api_key": api_key}).json() == EXPIRED


def test_key_of_an_ended_class_is_refused_as_expired(tmp_path):
    client, repo = _client(tmp_path)
    api_key, _, klass, _ = _redeemed_key(repo)
    repo.set_class_status(klass["id"], "ended")

    assert _key_check(client, {"api_key": api_key}).json() == EXPIRED


def test_key_of_a_class_session_not_yet_started_is_refused_as_not_started(tmp_path):
    client, repo = _client(tmp_path)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    api_key, _, _, _ = _redeemed_key(repo, session_at=tomorrow)

    assert _key_check(client, {"api_key": api_key}).json() == NOT_STARTED


def test_empty_or_whitespace_key_is_refused_as_invalid(tmp_path):
    client, _ = _client(tmp_path)

    assert _key_check(client, {"api_key": ""}).json() == INVALID
    assert _key_check(client, {"api_key": "   "}).json() == INVALID


def test_missing_wrong_or_malformed_service_credential_is_401_without_reading_the_body(tmp_path):
    client, repo = _client(tmp_path)
    api_key, _, _, _ = _redeemed_key(repo)

    calls = [
        client.post("/internal/key-check", json={"api_key": api_key}),
        client.post("/internal/key-check", content=b"not json"),
        _key_check(client, {"api_key": api_key}, credential="wrong-credential"),
        _key_check(client, {"api_key": api_key}, credential=""),
        client.post(
            "/internal/key-check",
            json={"api_key": api_key},
            headers={"Authorization": f"Basic {MCP_CREDENTIAL}"},
        ),
    ]

    for response in calls:
        assert response.status_code == 401
        assert "accepted" not in response.json()
        assert api_key not in response.text


def test_classroom_api_key_is_not_a_service_credential(tmp_path):
    client, repo = _client(tmp_path)
    api_key, _, _, _ = _redeemed_key(repo)

    response = _key_check(client, {"api_key": api_key}, credential=api_key)

    assert response.status_code == 401


def test_each_partner_service_calls_with_its_own_credential(tmp_path):
    client, repo = _client(tmp_path)
    api_key, _, _, _ = _redeemed_key(repo)

    assert _key_check(client, {"api_key": api_key}, credential=ROAD_TEST_CREDENTIAL).json()["accepted"] is True


def test_unreadable_body_gets_a_fixed_400_that_does_not_repeat_the_input(tmp_path):
    client, _ = _client(tmp_path)
    secret = "vcr_sk_" + "a" * 64
    headers = {"Authorization": f"Bearer {MCP_CREDENTIAL}"}
    bodies = [
        f"not json {secret}".encode(),
        f'["{secret}"]'.encode(),
        f'"{secret}"'.encode(),
        f'{{"key": "{secret}"}}'.encode(),
        b'{"api_key": 12345}',
        b'{"api_key": null}',
        f'{{"api_key": ["{secret}"]}}'.encode(),
        b"",
        b"\xff\xfe",
    ]

    responses = [client.post("/internal/key-check", content=body, headers=headers) for body in bodies]

    first = responses[0].json()
    for response in responses:
        assert response.status_code == 400
        assert response.json() == first
        assert secret not in response.text
        assert "12345" not in response.text


CONTRACT_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "key-check"


def _example(name: str):
    return json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))


def _shape(value):
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return type(value).__name__


def test_accepted_classroom_answer_matches_the_contract_example(tmp_path):
    client, repo = _client(tmp_path)
    api_key, _, _, _ = _redeemed_key(repo)
    example = _example("classroom-accepted.json")

    response = _key_check(client, {"api_key": api_key})

    assert response.status_code == 200
    assert _shape(response.json()) == _shape(example)
    assert response.json()["kind"] == example["kind"] == "classroom"
    assert response.json()["accepted"] is example["accepted"] is True


def test_refusal_matches_the_contract_example(tmp_path):
    client, _ = _client(tmp_path)

    response = _key_check(client, {"api_key": "vcr_sk_unknown"})

    assert response.status_code == 200
    assert response.json() == _example("refused.json")


def test_bad_request_matches_the_contract_example(tmp_path):
    client, _ = _client(tmp_path)

    response = client.post(
        "/internal/key-check",
        content=b"{}",
        headers={"Authorization": f"Bearer {MCP_CREDENTIAL}"},
    )

    assert response.status_code == 400
    assert response.json() == _example("bad-request.json")


def test_personal_api_key_is_not_a_service_credential(tmp_path):
    client, repo = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    personal_key = repo.issue_long_lived_key(teacher["id"])

    response = _key_check(client, {"api_key": "vcr_sk_whatever"}, credential=personal_key)

    assert response.status_code == 401


def test_both_hashes_of_a_partner_service_in_rotation_are_accepted(tmp_path):
    old, new = "old-road-test-credential", "new-road-test-credential"
    tokens = load_service_tokens(json.dumps({_sha256(old): "road-test", _sha256(new): "road-test"}))
    client, repo = _client(tmp_path, service_tokens=tokens)
    api_key, _, _, _ = _redeemed_key(repo)

    assert _key_check(client, {"api_key": api_key}, credential=old).json()["accepted"] is True
    assert _key_check(client, {"api_key": api_key}, credential=new).json()["accepted"] is True
    assert _key_check(client, {"api_key": api_key}, credential=MCP_CREDENTIAL).status_code == 401


def test_no_log_line_carries_the_whole_key(tmp_path, caplog):
    client, repo = _client(tmp_path)
    api_key, _, _, _ = _redeemed_key(repo)
    unknown = "vcr_sk_" + "b" * 64

    with caplog.at_level(logging.DEBUG):
        _key_check(client, {"api_key": api_key})
        _key_check(client, {"api_key": unknown})
        _key_check(client, {"api_key": api_key}, credential="wrong")

    for record in caplog.records:
        assert api_key not in record.getMessage()
        assert unknown not in record.getMessage()


# --- Personal API Key (ticket #94, ADR 0077, 0083) ---


def _teacher_with_classes(repo, email="teacher@school.edu", names=("Mon AM", "Wed PM")):
    teacher = repo.upsert_google_user(email, "Teacher")
    classes = [repo.create_class(teacher["id"], name, None) for name in names]
    return teacher, classes


def test_accepted_personal_api_key_names_user_and_the_classes_they_own(tmp_path):
    client, repo = _client(tmp_path)
    teacher, classes = _teacher_with_classes(repo)
    _teacher_with_classes(repo, email="other@school.edu", names=("Someone else's",))
    personal_key = repo.issue_long_lived_key(teacher["id"])

    response = _key_check(client, {"api_key": personal_key})

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "kind": "personal",
        "user_id": teacher["id"],
        "is_admin": False,
        "classes": [
            {"id": classes[0]["id"], "name": "Mon AM"},
            {"id": classes[1]["id"], "name": "Wed PM"},
        ],
    }


def test_admin_personal_api_key_lists_every_class_including_ended_ones(tmp_path):
    client, repo = _client(tmp_path)
    _, teacher_classes = _teacher_with_classes(repo)
    repo.set_class_status(teacher_classes[0]["id"], "ended")
    admin = repo.upsert_google_user("admin@school.edu", "Admin")
    personal_key = repo.issue_long_lived_key(admin["id"])

    answer = _key_check(client, {"api_key": personal_key}).json()

    assert answer["kind"] == "personal"
    assert answer["user_id"] == admin["id"]
    assert answer["is_admin"] is True
    assert answer["classes"] == [
        {"id": teacher_classes[0]["id"], "name": "Mon AM"},
        {"id": teacher_classes[1]["id"], "name": "Wed PM"},
    ]


def test_personal_api_key_of_someone_who_owns_no_class_is_accepted_with_no_classes(tmp_path):
    client, repo = _client(tmp_path)
    _teacher_with_classes(repo)
    student = repo.upsert_google_user("student@gmail.com", "Student")
    personal_key = repo.issue_long_lived_key(student["id"])

    assert _key_check(client, {"api_key": personal_key}).json() == {
        "accepted": True,
        "kind": "personal",
        "user_id": student["id"],
        "is_admin": False,
        "classes": [],
    }


def test_is_admin_reads_the_role_table_not_the_legacy_role_column(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    with repo._connect() as conn:  # a legacy users.role that disagrees with user_roles
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (teacher["id"],))
    personal_key = repo.issue_long_lived_key(teacher["id"])

    assert _key_check(client, {"api_key": personal_key}).json()["is_admin"] is False


def test_is_admin_is_false_for_a_legacy_admin_with_no_role_rows(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    personal_key = repo.issue_long_lived_key(teacher["id"])
    with repo._connect() as conn:  # a legacy users.role and no user_roles rows at all
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (teacher["id"],))
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (teacher["id"],))

    answer = _key_check(client, {"api_key": personal_key}).json()

    assert answer["is_admin"] is False
    assert [item["name"] for item in answer["classes"]] == ["Mon AM", "Wed PM"]


def test_personal_api_key_replaced_by_a_newer_one_is_refused_as_invalid(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    old_key = repo.issue_long_lived_key(teacher["id"])
    new_key = repo.issue_long_lived_key(teacher["id"])

    assert _key_check(client, {"api_key": old_key}).json() == INVALID
    assert _key_check(client, {"api_key": new_key}).json()["accepted"] is True


def test_personal_api_key_of_a_disabled_user_is_refused(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    personal_key = repo.issue_long_lived_key(teacher["id"])
    repo.update_user(teacher["id"], status="inactive")

    assert _key_check(client, {"api_key": personal_key}).json() == DISABLED


def test_accepted_personal_answer_matches_the_contract_example(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _ = _teacher_with_classes(repo)
    personal_key = repo.issue_long_lived_key(teacher["id"])
    example = _example("personal-accepted.json")

    answer = _key_check(client, {"api_key": personal_key}).json()

    assert _shape({k: v for k, v in answer.items() if k != "classes"}) == _shape(
        {k: v for k, v in example.items() if k != "classes"}
    )
    assert [_shape(item) for item in answer["classes"]] == [_shape(example["classes"][0])] * len(answer["classes"])
    assert answer["kind"] == example["kind"] == "personal"
    assert answer["accepted"] is example["accepted"] is True


class _Clock:
    """A settable time source, so no test waits for real seconds to pass."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _last_used_at(repo, api_key: str) -> str | None:
    with repo._connect() as conn:
        row = conn.execute(
            "SELECT last_used_at FROM api_keys WHERE key_hash = ?", (_sha256(api_key),)
        ).fetchone()
    return row["last_used_at"]


def test_a_second_pass_within_60_seconds_does_not_write_last_used_at(tmp_path):
    clock = _Clock(datetime.now(UTC))
    client, repo = _client(tmp_path, clock=clock)
    api_key, _, _, _ = _redeemed_key(repo)
    start = clock.now = datetime.now(UTC) + timedelta(seconds=1)

    assert _key_check(client, {"api_key": api_key}).json()["accepted"] is True
    assert _last_used_at(repo, api_key) == start.isoformat()

    clock.now = start + timedelta(seconds=59)
    assert _key_check(client, {"api_key": api_key}).json()["accepted"] is True
    assert _last_used_at(repo, api_key) == start.isoformat()


def test_a_pass_60_seconds_after_the_last_write_writes_last_used_at(tmp_path):
    clock = _Clock(datetime.now(UTC))
    client, repo = _client(tmp_path, clock=clock)
    api_key, _, _, _ = _redeemed_key(repo)
    start = clock.now = datetime.now(UTC) + timedelta(seconds=1)
    _key_check(client, {"api_key": api_key})

    clock.now = start + timedelta(seconds=30)
    _key_check(client, {"api_key": api_key})
    clock.now = start + timedelta(seconds=61)
    assert _key_check(client, {"api_key": api_key}).json()["accepted"] is True

    assert _last_used_at(repo, api_key) == (start + timedelta(seconds=61)).isoformat()
