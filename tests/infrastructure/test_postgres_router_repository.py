import os
from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.factory import build_router_repository


def _settings() -> RouterSettings:
    return RouterSettings(
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-secret",
        ),
        database=DatabaseSettings(
            url=os.environ["TEST_DATABASE_URL"],
            archive_dir="/tmp/vcr-archive",
        ),
    )


@pytest.fixture
def postgres_repo():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is not set")
    repo = build_router_repository(_settings())
    yield repo
    with repo._connect() as conn:
        conn.execute(
            """
            TRUNCATE prompt_logs_archive, prompt_logs, api_keys, session_redemptions,
            class_members, class_sessions, classes, user_roles, users
            RESTART IDENTITY CASCADE
            """
        )


def test_postgres_session_key_redeem_verify_and_prompt_log(postgres_repo):
    repo = postgres_repo
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")
    assert teacher["role"] == "teacher"

    klass = repo.create_class(
        teacher_id=teacher["id"],
        name="AI 課程",
        ends_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        api_key_ttl_hours=2,
    )
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    redeemed = repo.redeem_invite(session["invite_code"], student["id"])

    context = repo.verify_api_key_context(redeemed["api_key"])
    assert context is not None
    assert context.user_id == student["id"]
    assert context.class_id == klass["id"]

    repo.log_prompt(context, "user: hello", "user: hello", "fake-model", "ok", "127.0.0.1")
    logs = repo.list_prompt_logs(teacher["id"], klass["id"])
    assert logs[0]["raw_prompt"] == "user: hello"


def test_postgres_archive_moves_logs_to_archive_table(postgres_repo):
    repo = postgres_repo
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    ended = repo.create_class(teacher["id"], "Ended", None, 2)
    repo.set_class_status(ended["id"], "ended")
    repo.set_class_status(ended["id"], "active")
    ended_session = repo.create_class_session(ended["id"], teacher["id"], "Ended Session")
    repo.set_class_status(ended["id"], "ended")
    repo.set_class_status(ended["id"], "active")
    ended_key = repo.redeem_invite(ended_session["invite_code"], student["id"])["api_key"]
    repo.set_class_status(ended["id"], "ended")
    context = repo.verify_api_key_context(ended_key)
    assert context is not None
    repo.log_prompt(context, "ended log", "ended log", "fake-model", "ok", None)

    result = repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), retention_days=30)
    assert result["archived"] == 1
    assert repo.list_prompt_logs(teacher["id"], ended["id"]) == []

    with repo._connect() as conn:
        archived = conn.execute(
            "SELECT raw_prompt FROM prompt_logs_archive WHERE raw_prompt = %s",
            ("ended log",),
        ).fetchall()
    assert len(archived) == 1
