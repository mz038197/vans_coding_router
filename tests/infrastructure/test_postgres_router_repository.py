import os
from datetime import UTC, datetime, timedelta

import pytest

from src.domain.auto_tier import TierSelection
from src.domain.session_model_allowlist import template_model_ids
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.factory import build_router_repository
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template


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


def test_postgres_portal_session_roundtrip(postgres_repo):
    user = postgres_repo.upsert_google_user("student@gmail.com", "Student")
    token, issued = postgres_repo.create_portal_session(user["id"], "Chrome on Linux")

    authenticated = postgres_repo.authenticate_portal_session(token)

    assert authenticated is not None
    assert authenticated.session_id == issued.session_id
    assert postgres_repo.list_portal_sessions(user["id"])[0]["browser_description"] == "Chrome on Linux"


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
    context = repo.verify_api_key_context(ended_key)
    assert context is not None
    repo.set_class_status(ended["id"], "ended")
    repo.log_prompt(context, "ended log", "ended log", "fake-model", "ok", None)
    with repo._connect() as conn:
        conn.execute(
            "UPDATE prompt_logs SET created_at = %s WHERE raw_prompt = %s",
            ("2026-05-01T00:00:00+00:00", "ended log"),
        )

    result = repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), archive_after_days=15)
    assert result["archived"] == 1
    assert repo.list_prompt_logs(teacher["id"], ended["id"]) == []

    with repo._connect() as conn:
        archived = conn.execute(
            "SELECT raw_prompt FROM prompt_logs_archive WHERE raw_prompt = %s",
            ("ended log",),
        ).fetchall()
    assert len(archived) == 1

    cleared = repo.clear_all_archived_prompt_logs()
    assert cleared["deleted"] == 1
    with repo._connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM prompt_logs_archive").fetchone()["n"] == 0


def _student_context(repo):
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "Tiers", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    context = repo.verify_api_key_context(repo.redeem_invite(session["invite_code"], student["id"])["api_key"])
    assert context is not None
    return teacher, klass, context


def test_postgres_prompt_log_keeps_tier_name_and_confidence(postgres_repo):
    repo = postgres_repo
    teacher, klass, context = _student_context(repo)
    repo.log_prompt(context, "tiered", "tiered", "openrouter@vendor/strong", "ok", None, tier=TierSelection("t-strong", "進階", 0.92))
    repo.log_prompt(context, "untiered", "untiered", "openrouter@vendor/light", "ok", None)

    logs = repo.list_prompt_logs(teacher["id"], klass["id"])

    assert sorted((log["raw_prompt"], log["tier_name"], log["tier_confidence"]) for log in logs) == [
        ("tiered", "進階", 0.92),
        ("untiered", None, None),
    ]


def test_postgres_archive_keeps_tier_name_and_confidence(postgres_repo):
    repo = postgres_repo
    _, _, context = _student_context(repo)
    repo.log_prompt(context, "tiered", "tiered", "openrouter@vendor/strong", "ok", None, tier=TierSelection("t-strong", "進階", 0.92))
    repo.log_prompt(context, "untiered", "untiered", "openrouter@vendor/light", "ok", None)
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = %s", ("2026-05-01T00:00:00+00:00",))

    assert repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), archive_after_days=15)["archived"] == 2

    with repo._connect() as conn:
        rows = conn.execute(
            "SELECT raw_prompt, tier_name, tier_confidence FROM prompt_logs_archive ORDER BY raw_prompt"
        ).fetchall()
    assert [(r["raw_prompt"], r["tier_name"], r["tier_confidence"]) for r in rows] == [
        ("tiered", "進階", 0.92),
        ("untiered", None, None),
    ]


def test_postgres_nickname_redeem_identity_is_per_class(postgres_repo):
    repo = postgres_repo
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    first = repo.redeem_invite_with_nickname(session["invite_code"], "Ada")
    again = repo.redeem_invite_with_nickname(session["invite_code"], "Ada")
    assert first["api_key"] == again["api_key"]

    other = repo.create_class(teacher["id"], "Other", None, 2)
    other_session = repo.create_class_session(other["id"], teacher["id"], "Week 1")
    other_redeem = repo.redeem_invite_with_nickname(other_session["invite_code"], "Ada")
    user_a = repo.verify_api_key_context(first["api_key"]).user_id
    user_b = repo.verify_api_key_context(other_redeem["api_key"]).user_id
    assert user_a != user_b


def test_postgres_session_seat_limit_blocks_new_identities(postgres_repo):
    repo = postgres_repo
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    assert session["seat_limit"] == 60
    repo.update_class_session(klass["id"], session["id"], seat_limit=1)
    first = repo.redeem_invite_with_nickname(session["invite_code"], "Ada")
    assert first["api_key"].startswith("vcr_sk_")
    with pytest.raises(ValueError, match="座位已滿"):
        repo.redeem_invite_with_nickname(session["invite_code"], "Bob")
    again = repo.redeem_invite_with_nickname(session["invite_code"], "Ada")
    assert again["api_key"] == first["api_key"]
    items = repo.list_class_sessions(klass["id"])
    assert "nickname_seat_count" not in items[0]
    assert items[0]["redemption_count"] == 1
    assert items[0]["seat_limit"] == 1
    student = repo.upsert_google_user("student@gmail.com", "Student")
    with pytest.raises(ValueError, match="無法領取"):
        repo.redeem_invite(session["invite_code"], student["id"])


def test_postgres_web_search_switch_is_off_until_turned_on(postgres_repo):
    repo = postgres_repo
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    assert session["web_search_enabled"] is False
    assert repo.is_web_search_enabled(session["id"]) is False
    updated = repo.update_class_session(klass["id"], session["id"], web_search_enabled=True)
    assert updated["web_search_enabled"] is True
    assert repo.is_web_search_enabled(session["id"]) is True
    repo.update_class_session(klass["id"], session["id"], web_search_enabled=False)
    assert repo.is_web_search_enabled(session["id"]) is False


def _carries_auto_tiers(document) -> bool:
    return any(
        "autoTiers" in provider or any("autoTier" in model for model in provider.get("models", []))
        for provider in document
    )


def test_postgres_sitting_filled_from_the_starter_gets_no_auto_tiers(postgres_repo):
    assert _carries_auto_tiers(load_vans_template()), "the starter ships default Auto Tiers"
    repo = postgres_repo
    owner = repo.upsert_google_user("owner@gmail.com", "Owner")
    klass = repo.create_class(owner["id"], "No template", None, 2)
    created = repo.create_class_session(klass["id"], owner["id"], "Week 1")
    backfilled = repo.create_class_session(klass["id"], owner["id"], "Week 2")
    with repo._connect() as conn:
        conn.execute(
            "UPDATE class_sessions SET session_chat_language_models_json = NULL WHERE id = %s",
            (backfilled["id"],),
        )
    reopened = build_router_repository(_settings())

    sittings = {s["id"]: s for s in reopened.list_class_sessions(klass["id"])}

    for session_id in (created["id"], backfilled["id"]):
        document = sittings[session_id]["session_chat_language_models"]
        assert template_model_ids(document) == template_model_ids(load_vans_template())
        assert not _carries_auto_tiers(document)
