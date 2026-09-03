from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from src.domain.session_model_allowlist import template_model_ids
from src.infrastructure.config import AuthSettings, DatabaseSettings, PromptLogSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template


def _settings(tmp_path) -> RouterSettings:
    return RouterSettings(
        database=DatabaseSettings(
            path=str(tmp_path / "router.db"),
            archive_dir=str(tmp_path / "archive"),
        )
    )


def test_portal_session_authenticates_with_server_issued_opaque_token(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(
            path=str(tmp_path / "router.db"),
            archive_dir=str(tmp_path / "archive"),
        )
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    user = repo.upsert_google_user("teacher@example.com", "Teacher")

    token, issued = repo.create_portal_session(user["id"], "Chrome on Windows")

    authenticated = repo.authenticate_portal_session(token)
    assert authenticated is not None
    assert authenticated.session_id == issued.session_id
    assert authenticated.user_id == user["id"]
    assert authenticated.browser_description == "Chrome on Windows"
    assert repo.authenticate_portal_session(str(user["id"])) is None


def test_user_can_list_and_revoke_one_portal_session(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(
            path=str(tmp_path / "router.db"),
            archive_dir=str(tmp_path / "archive"),
        )
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    user = repo.upsert_google_user("teacher@example.com", "Teacher")
    first_token, first = repo.create_portal_session(user["id"], "Chrome on Windows")
    second_token, second = repo.create_portal_session(user["id"], "Safari on macOS")

    sessions = repo.list_portal_sessions(user["id"])
    assert {item["id"] for item in sessions} == {first.session_id, second.session_id}
    assert all("token" not in item and "token_hash" not in item for item in sessions)

    assert repo.revoke_portal_session(user["id"], first.session_id, "user_logout")
    assert repo.authenticate_portal_session(first_token) is None
    assert repo.authenticate_portal_session(second_token) is not None


def test_eleventh_portal_session_revokes_least_recently_active(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(
            path=str(tmp_path / "router.db"),
            archive_dir=str(tmp_path / "archive"),
        )
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    user = repo.upsert_google_user("teacher@example.com", "Teacher")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    issued = [
        repo.create_portal_session(
            user["id"],
            f"Browser {index}",
            now=start + timedelta(minutes=index),
        )
        for index in range(11)
    ]

    assert repo.authenticate_portal_session(issued[0][0], now=start + timedelta(minutes=11)) is None
    assert len(repo.list_portal_sessions(user["id"], now=start + timedelta(minutes=11))) == 10


def test_portal_session_has_idle_and_absolute_expiry_and_throttled_activity(tmp_path):
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    user = repo.upsert_google_user("student@gmail.com", "Student")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    token, _ = repo.create_portal_session(user["id"], "Firefox on Linux", now=start)

    assert repo.authenticate_portal_session(token, now=start + timedelta(minutes=4)) is not None
    unchanged = repo.list_portal_sessions(user["id"], now=start + timedelta(minutes=4))[0]
    assert unchanged["last_seen_at"] == start.isoformat()

    assert repo.authenticate_portal_session(token, now=start + timedelta(minutes=5)) is not None
    refreshed = repo.list_portal_sessions(user["id"], now=start + timedelta(minutes=5))[0]
    assert refreshed["last_seen_at"] == (start + timedelta(minutes=5)).isoformat()
    assert repo.authenticate_portal_session(token, now=start + timedelta(hours=12, minutes=5)) is None

    absolute_token, _ = repo.create_portal_session(user["id"], "Firefox on Linux", now=start)
    assert repo.authenticate_portal_session(
        absolute_token,
        now=start + timedelta(days=7),
    ) is None


def test_non_activity_validation_does_not_refresh_last_seen(tmp_path):
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    user = repo.upsert_google_user("student@gmail.com", "Student")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    token, _ = repo.create_portal_session(user["id"], "Chrome", now=start)

    assert repo.authenticate_portal_session(
        token,
        now=start + timedelta(minutes=10),
        refresh_activity=False,
    ) is not None
    session = repo.list_portal_sessions(user["id"], now=start + timedelta(minutes=10))[0]
    assert session["last_seen_at"] == start.isoformat()


def test_suspending_user_revokes_sessions_and_disables_keys(tmp_path):
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    user = repo.upsert_google_user("teacher@school.edu", "Teacher")
    token, _ = repo.create_portal_session(user["id"], "Chrome")
    api_key = repo.issue_long_lived_key(user["id"])

    repo.update_user(user["id"], status="inactive")

    assert repo.authenticate_portal_session(token) is None
    assert repo.verify_api_key(api_key)[0] is False


def test_portal_session_events_exclude_secrets_and_old_sessions_are_purged(tmp_path):
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    user = repo.upsert_google_user("student@gmail.com", "Student")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    token, session = repo.create_portal_session(user["id"], "Safari", now=start)
    repo.revoke_portal_session(
        user["id"],
        session.session_id,
        "user_logout",
        now=start + timedelta(hours=1),
    )

    with sqlite3.connect(settings.database.path) as conn:
        conn.row_factory = sqlite3.Row
        events = [dict(row) for row in conn.execute("SELECT * FROM portal_session_events")]
        assert [event["event_type"] for event in events] == [
            "session_created",
            "session_revoked_user_logout",
        ]
        assert all(token not in str(event) for event in events)

    assert repo.purge_portal_sessions(now=start + timedelta(days=31, hours=2)) == 1


def test_sqlite_session_key_redeem_verify_and_prompt_log(tmp_path):
    settings = RouterSettings(
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-secret",
        ),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)

    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")
    assert teacher["role"] == "teacher"
    assert student["role"] == "student"

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
    assert context.session_id == session["id"]

    repo.log_prompt(context, "user: hello", "user: hello", "fake-model", "ok", "127.0.0.1")
    logs = repo.list_prompt_logs(teacher["id"], klass["id"])
    assert logs[0]["user_name"] == "Student"
    assert logs[0]["user_email"] == "student@gmail.com"
    assert logs[0]["raw_prompt"] == "user: hello"


def test_prompt_logs_can_be_filtered_by_time_range(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    redeemed = repo.redeem_invite(session["invite_code"], student["id"])
    context = repo.verify_api_key_context(redeemed["api_key"])
    assert context is not None

    repo.log_prompt(context, "old prompt", "old prompt", "fake-model", "ok", None)
    repo.log_prompt(context, "new prompt", "new prompt", "fake-model", "ok", None)
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-01-01T00:00:00+00:00", "old prompt"))
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-02-01T00:00:00+00:00", "new prompt"))

    logs = repo.list_prompt_logs(
        teacher_id=teacher["id"],
        class_id=klass["id"],
        start_at="2026-01-15T00:00:00+00:00",
        end_at="2026-02-15T00:00:00+00:00",
    )

    assert [log["raw_prompt"] for log in logs] == ["new prompt"]


def test_archive_prompt_logs_moves_retention_and_ended_class_logs_to_year_files(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")

    active = repo.create_class(teacher["id"], "Active", None, 2)
    ended = repo.create_class(teacher["id"], "Ended", None, 2)
    repo.set_class_status(ended["id"], "ended")
    active_session = repo.create_class_session(active["id"], teacher["id"], "Active Session")
    repo.set_class_status(ended["id"], "active")
    ended_session = repo.create_class_session(ended["id"], teacher["id"], "Ended Session")
    repo.set_class_status(ended["id"], "ended")

    active_key = repo.redeem_invite(active_session["invite_code"], student["id"])["api_key"]
    repo.set_class_status(ended["id"], "active")
    ended_key = repo.redeem_invite(ended_session["invite_code"], student["id"])["api_key"]
    repo.set_class_status(ended["id"], "ended")

    active_context = repo.verify_api_key_context(active_key)
    assert active_context is not None
    ended_context = active_context.__class__(
        user_id=student["id"],
        email="student@example.com",
        name="Student",
        role="student",
        session_id=ended_session["id"],
        class_id=ended["id"],
    )
    repo.log_prompt(active_context, "old active", "old active", "fake-model", "ok", None)
    repo.log_prompt(ended_context, "recent ended", "recent ended", "fake-model", "ok", None)
    repo.log_prompt(active_context, "recent active", "recent active", "fake-model", "ok", None)
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2025-01-01T00:00:00+00:00", "old active"))
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-06-01T00:00:00+00:00", "recent ended"))
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-06-10T00:00:00+00:00", "recent active"))

    result = repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), archive_after_days=15)

    assert result["archived"] == 2
    remaining = repo.list_prompt_logs(teacher["id"], active["id"])
    assert [log["raw_prompt"] for log in remaining] == ["recent active"]
    with sqlite3.connect(tmp_path / "archive" / "archive_2025.db") as conn:
        archived_2025 = conn.execute("SELECT raw_prompt, archived_at FROM prompt_logs_archive").fetchall()
    with sqlite3.connect(tmp_path / "archive" / "archive_2026.db") as conn:
        archived_2026 = conn.execute("SELECT raw_prompt, archived_at FROM prompt_logs_archive").fetchall()
    assert archived_2025[0][0] == "old active"
    assert archived_2025[0][1]
    assert archived_2026[0][0] == "recent ended"


def test_purge_archived_prompt_logs_deletes_by_created_at(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "Active", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    context = repo.verify_api_key_context(key)
    assert context is not None
    repo.log_prompt(context, "keep me", "keep me", "fake-model", "ok", None)
    repo.log_prompt(context, "delete me", "delete me", "fake-model", "ok", None)
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-05-01T00:00:00+00:00", "delete me"))
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-06-10T00:00:00+00:00", "keep me"))
    now = datetime(2026, 6, 18, tzinfo=UTC)
    assert repo.archive_prompt_logs(now=now, archive_after_days=15)["archived"] == 1
    purged = repo.purge_archived_prompt_logs(now=now, delete_after_days=30)
    assert purged["deleted"] == 1
    with sqlite3.connect(tmp_path / "archive" / "archive_2026.db") as conn:
        rows = conn.execute("SELECT raw_prompt FROM prompt_logs_archive").fetchall()
    assert rows == []


def test_clear_all_archived_prompt_logs(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    ended = repo.create_class(teacher["id"], "Ended", None, 2)
    session = repo.create_class_session(ended["id"], teacher["id"], "Session")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    context = repo.verify_api_key_context(key)
    assert context is not None
    repo.log_prompt(context, "ended log", "ended log", "fake-model", "ok", None)
    repo.set_class_status(ended["id"], "ended")
    assert repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC))["archived"] == 1
    cleared = repo.clear_all_archived_prompt_logs()
    assert cleared["deleted"] == 1
    with sqlite3.connect(tmp_path / "archive" / "archive_2026.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM prompt_logs_archive").fetchone()[0]
    assert count == 0


def test_delete_prompt_logs_for_users_keeps_other_users(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    user_a = repo.upsert_google_user("a@example.com", "A")
    user_b = repo.upsert_google_user("b@example.com", "B")
    klass = repo.create_class(teacher["id"], "Class", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    key_a = repo.redeem_invite(session["invite_code"], user_a["id"])["api_key"]
    key_b = repo.redeem_invite(session["invite_code"], user_b["id"])["api_key"]
    ctx_a = repo.verify_api_key_context(key_a)
    ctx_b = repo.verify_api_key_context(key_b)
    assert ctx_a is not None and ctx_b is not None
    repo.log_prompt(ctx_a, "a-live", "a-live", "fake-model", "ok", None)
    repo.log_prompt(ctx_b, "b-live", "b-live", "fake-model", "ok", None)
    repo.set_class_status(klass["id"], "ended")
    assert repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC))["archived"] == 2

    # new class for fresh live logs after archive
    live_class = repo.create_class(teacher["id"], "Live", None, 2)
    live_session = repo.create_class_session(live_class["id"], teacher["id"], "Live Session")
    key_a2 = repo.redeem_invite(live_session["invite_code"], user_a["id"])["api_key"]
    key_b2 = repo.redeem_invite(live_session["invite_code"], user_b["id"])["api_key"]
    ctx_a2 = repo.verify_api_key_context(key_a2)
    ctx_b2 = repo.verify_api_key_context(key_b2)
    assert ctx_a2 is not None and ctx_b2 is not None
    repo.log_prompt(ctx_a2, "a-again", "a-again", "fake-model", "ok", None)
    repo.log_prompt(ctx_b2, "b-again", "b-again", "fake-model", "ok", None)

    usage = {item["user_id"]: item for item in repo.prompt_log_usage_by_user()}
    assert usage[user_a["id"]]["live_count"] == 1
    assert usage[user_a["id"]]["archive_count"] == 1
    assert usage[user_b["id"]]["live_count"] == 1
    assert usage[user_b["id"]]["archive_count"] == 1

    assert repo.delete_prompt_logs_for_users([]) == {"deleted_live": 0, "deleted_archive": 0}
    result = repo.delete_prompt_logs_for_users([user_a["id"]])
    assert result == {"deleted_live": 1, "deleted_archive": 1}

    remaining = repo.list_prompt_logs(teacher["id"], live_class["id"])
    assert [row["raw_prompt"] for row in remaining] == ["b-again"]
    with sqlite3.connect(tmp_path / "archive" / "archive_2026.db") as conn:
        archived = [row[0] for row in conn.execute("SELECT raw_prompt FROM prompt_logs_archive").fetchall()]
    assert archived == ["b-live"]
    usage_after = {item["user_id"]: item for item in repo.prompt_log_usage_by_user()}
    assert usage_after[user_a["id"]]["total_count"] == 0
    assert usage_after[user_b["id"]]["total_count"] == 2


def test_session_key_hash_updates_when_session_secret_rotates(tmp_path):
    settings = RouterSettings(
        auth=AuthSettings(session_secret="secret-a"),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")
    klass = repo.create_class(
        teacher["id"],
        "AI",
        (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        2,
    )
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    repo.redeem_invite(session["invite_code"], student["id"])

    repo.settings = RouterSettings(
        auth=AuthSettings(session_secret="secret-b"),
        database=settings.database,
    )
    rotated = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    context = repo.verify_api_key_context(rotated)
    assert context is not None
    assert context.user_id == student["id"]


def test_verify_api_key_strips_surrounding_whitespace(tmp_path):
    settings = RouterSettings(
        auth=AuthSettings(session_secret="test-secret"),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]

    assert repo.verify_api_key_context(f"  {key}  ") is not None
    assert repo.verify_api_key_context(f"{key}\n") is not None


def test_create_session_with_session_at_sets_expires_at(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session_at = datetime(2026, 6, 21, 14, 0, tzinfo=UTC).isoformat()
    session = repo.create_class_session(
        klass["id"],
        teacher["id"],
        "第一堂",
        ttl_hours=3,
        session_at=session_at,
    )
    assert session["session_at"] == session_at
    assert session["name"] == "第一堂"
    assert session["expires_at"] == datetime(2026, 6, 21, 17, 0, tzinfo=UTC).isoformat()


def test_create_session_requires_name(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    with pytest.raises(ValueError, match="課堂名稱"):
        repo.create_class_session(klass["id"], teacher["id"], "   ")


def test_update_session_name(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Old Name")
    updated = repo.update_class_session(klass["id"], session["id"], name="New Name")
    assert updated is not None
    assert updated["name"] == "New Name"


def test_session_model_allowlist_round_trip(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    template = load_vans_template()
    assert session["session_chat_language_models"] == template
    assert session["model_allowlist"] == template_model_ids(template)
    assert repo.get_session_model_allowlist(session["id"]) == template_model_ids(template)

    updated = repo.update_class_session(
        klass["id"],
        session["id"],
        model_allowlist=["ollama_cloud@minimax-m3:cloud"],
    )
    assert updated is not None
    assert updated["model_allowlist"] == ["ollama_cloud@minimax-m3:cloud"]
    assert repo.get_session_model_allowlist(session["id"]) == ["ollama_cloud@minimax-m3:cloud"]

    emptied = repo.update_class_session(klass["id"], session["id"], model_allowlist=[])
    assert emptied is not None
    assert emptied["model_allowlist"] == []
    assert repo.get_session_model_allowlist(session["id"]) == []

    restored = repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=template,
    )
    assert restored is not None
    assert restored["session_chat_language_models"] == template
    assert restored["model_allowlist"] == template_model_ids(template)
    assert repo.get_session_model_allowlist(session["id"]) == template_model_ids(template)


def test_get_active_keys_includes_session_name(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI Course", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Lesson 1")
    repo.redeem_invite(session["invite_code"], student["id"])
    keys = repo.get_active_keys(student["id"])
    session_keys = [k for k in keys if k["session_id"]]
    assert len(session_keys) == 1
    assert session_keys[0]["class_name"] == "AI Course"
    assert session_keys[0]["session_name"] == "Lesson 1"
    assert session_keys[0]["session_at"] is not None


def test_list_class_sessions_includes_redemption_count(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    repo.redeem_invite(session["invite_code"], student["id"])
    items = repo.list_class_sessions(klass["id"])
    assert len(items) == 1
    assert items[0]["redemption_count"] == 1


def test_redeem_same_invite_returns_same_key(tmp_path):
    settings = RouterSettings(
        auth=AuthSettings(session_secret="test-secret"),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    first = repo.redeem_invite(session["invite_code"], student["id"])
    second = repo.redeem_invite(session["invite_code"], student["id"])
    assert first["api_key"] == second["api_key"]
    assert repo.verify_api_key_context(first["api_key"]) is not None


def test_end_session_invalidates_key_and_blocks_redeem(tmp_path):
    settings = RouterSettings(
        auth=AuthSettings(session_secret="test-secret"),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    redeemed = repo.redeem_invite(session["invite_code"], student["id"])
    assert repo.verify_api_key_context(redeemed["api_key"]) is not None

    ended = repo.update_class_session(klass["id"], session["id"], status="ended")
    assert ended["status"] == "ended"
    assert parse_dt_iso(ended["expires_at"]) <= datetime.now(UTC)
    assert repo.verify_api_key_context(redeemed["api_key"]) is None
    with pytest.raises(ValueError):
        repo.redeem_invite(session["invite_code"], student["id"])

    with pytest.raises(ValueError, match="到期時間"):
        repo.update_class_session(klass["id"], session["id"], status="active")

    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    reopened = repo.update_class_session(klass["id"], session["id"], expires_at=future)
    assert reopened["status"] == "active"
    assert parse_dt_iso(reopened["expires_at"]) > datetime.now(UTC)
    assert repo.verify_api_key_context(redeemed["api_key"]) is not None


def test_backfill_aligns_ended_session_future_expires(tmp_path):
    settings = RouterSettings(
        auth=AuthSettings(session_secret="test-secret"),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    db_path = str(tmp_path / "router.db")
    repo = SqliteRouterRepository(db_path, settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Legacy Ended")
    redeemed = repo.redeem_invite(session["invite_code"], student["id"])
    future = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE class_sessions SET status = 'ended', expires_at = ? WHERE id = ?",
            (future, session["id"]),
        )
        conn.execute(
            "UPDATE api_keys SET expires_at = ? WHERE session_id = ?",
            (future, session["id"]),
        )
        conn.commit()

    repo2 = SqliteRouterRepository(db_path, settings)
    rows = repo2.list_class_sessions(klass["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "ended"
    assert parse_dt_iso(rows[0]["expires_at"]) <= datetime.now(UTC)
    assert repo2.verify_api_key_context(redeemed["api_key"]) is None


def test_agent_action_audit_migrates_to_nullable_non_session_targets(tmp_path):
    settings = _settings(tmp_path)
    db_path = str(tmp_path / "router.db")
    repo = SqliteRouterRepository(db_path, settings)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    repo.record_agent_action_audit(
        actor_user_id=teacher["id"],
        action="update_session_capabilities",
        class_id=klass["id"],
        session_id=session["id"],
        arguments={"tts_enabled": False},
        invocation_channel="webmcp",
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE agent_action_audits RENAME TO agent_action_audits_old")
        conn.execute(
            """
            CREATE TABLE agent_action_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER NOT NULL REFERENCES users(id),
                action TEXT NOT NULL,
                class_id INTEGER NOT NULL REFERENCES classes(id),
                session_id INTEGER NOT NULL REFERENCES class_sessions(id),
                arguments_json TEXT NOT NULL,
                invocation_channel TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO agent_action_audits(
                id, actor_user_id, action, class_id, session_id, arguments_json,
                invocation_channel, occurred_at
            )
            SELECT id, actor_user_id, action, class_id, session_id, arguments_json,
                   invocation_channel, occurred_at
            FROM agent_action_audits_old
            """
        )
        conn.execute("DROP TABLE agent_action_audits_old")
        conn.execute(
            "CREATE INDEX agent_action_audits_actor_user_id ON agent_action_audits(actor_user_id)"
        )
        conn.execute(
            "CREATE INDEX agent_action_audits_target ON agent_action_audits(class_id, session_id)"
        )
        conn.commit()

    migrated = SqliteRouterRepository(db_path, settings)
    migrated.record_agent_action_audit(
        actor_user_id=teacher["id"],
        action="release_key_quarantine",
        class_id=None,
        session_id=None,
        arguments={"provider": "ollama_cloud", "key_index": 0},
        invocation_channel="webmcp",
    )
    audits = migrated.list_agent_action_audits()
    assert len(audits) == 2
    assert audits[0]["class_id"] is None
    assert audits[0]["session_id"] is None


def test_update_session_expires_at_syncs_api_keys(tmp_path):
    settings = RouterSettings(
        auth=AuthSettings(session_secret="test-secret"),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Test Session")
    redeemed = repo.redeem_invite(session["invite_code"], student["id"])
    new_expires = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    updated = repo.update_class_session(klass["id"], session["id"], expires_at=new_expires)
    assert updated is not None
    keys = repo.get_active_keys(student["id"])
    session_key = next(k for k in keys if k["session_id"] == session["id"])
    assert parse_dt_iso(session_key["expires_at"]) == parse_dt_iso(updated["expires_at"])
    assert repo.verify_api_key_context(redeemed["api_key"]) is not None


def parse_dt_iso(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
