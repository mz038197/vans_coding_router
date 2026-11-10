from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from src.domain.auto_tier import TierSelection, without_auto_tiers
from src.domain.session_model_allowlist import template_model_ids
from src.infrastructure.config import AuthSettings, DatabaseSettings, PromptLogSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template
from tests.infrastructure.fresh_schema_snapshot import SHARED_TABLE_COLUMNS


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
    klass = repo.create_class(teacher["id"], "AI", None)
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


def test_archive_prompt_logs_moves_old_logs_and_keeps_young_logs_on_an_ended_class(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")

    active = repo.create_class(teacher["id"], "Active", None)
    ended = repo.create_class(teacher["id"], "Ended", None)
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
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-06-16T00:00:00+00:00", "recent ended"))
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-06-10T00:00:00+00:00", "recent active"))

    result = repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), archive_after_days=15)

    assert result["archived"] == 1
    assert [log["raw_prompt"] for log in repo.list_prompt_logs(teacher["id"], active["id"])] == ["recent active"]
    assert [log["raw_prompt"] for log in repo.list_prompt_logs(teacher["id"], ended["id"])] == ["recent ended"]
    with sqlite3.connect(tmp_path / "archive" / "archive_2025.db") as conn:
        archived_2025 = conn.execute("SELECT raw_prompt, archived_at FROM prompt_logs_archive").fetchall()
    assert [row[0] for row in archived_2025] == ["old active"]
    assert archived_2025[0][1]


def test_archive_keeps_the_tier_name_and_confidence_in_an_older_archive_file(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    (tmp_path / "archive").mkdir()
    with sqlite3.connect(tmp_path / "archive" / "archive_2025.db") as conn:
        conn.execute(
            """
            CREATE TABLE prompt_logs_archive (
                id INTEGER, user_id INTEGER, class_id INTEGER, session_id INTEGER,
                raw_prompt TEXT NOT NULL, final_prompt TEXT NOT NULL, model TEXT NOT NULL,
                status TEXT NOT NULL, client_ip TEXT, created_at TEXT NOT NULL,
                archived_at TEXT NOT NULL, message_preview TEXT, messages_json TEXT
            )
            """
        )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "Active", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    context = repo.verify_api_key_context(repo.redeem_invite(session["invite_code"], student["id"])["api_key"])
    repo.log_prompt(context, "tiered", "tiered", "openrouter@vendor/strong", "ok", None, tier=TierSelection("t-strong", "進階", 0.92))
    repo.log_prompt(context, "untiered", "untiered", "openrouter@vendor/light", "ok", None)
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = ?", ("2025-01-01T00:00:00+00:00",))

    assert repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), archive_after_days=15)["archived"] == 2

    with sqlite3.connect(tmp_path / "archive" / "archive_2025.db") as conn:
        rows = conn.execute(
            "SELECT raw_prompt, tier_name, tier_confidence FROM prompt_logs_archive ORDER BY raw_prompt"
        ).fetchall()
    assert rows == [("tiered", "進階", 0.92), ("untiered", None, None)]


def _archive_two_logs_with_token_counts(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "Active", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    context = repo.verify_api_key_context(repo.redeem_invite(session["invite_code"], student["id"])["api_key"])
    repo.log_prompt(context, "counted", "counted", "fake-model", "ok", None, 12, 30, 42)
    repo.log_prompt(context, "uncounted", "uncounted", "fake-model", "error", None)
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = ?", ("2025-01-01T00:00:00+00:00",))

    assert repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), archive_after_days=15)["archived"] == 2

    with sqlite3.connect(tmp_path / "archive" / "archive_2025.db") as conn:
        return conn.execute(
            "SELECT raw_prompt, prompt_tokens, completion_tokens, total_tokens"
            " FROM prompt_logs_archive ORDER BY raw_prompt"
        ).fetchall()


def test_archive_keeps_prompt_log_token_counts(tmp_path):
    assert _archive_two_logs_with_token_counts(tmp_path) == [("counted", 12, 30, 42), ("uncounted", 0, 0, 0)]


def test_archive_adds_token_columns_to_an_older_archive_file(tmp_path):
    (tmp_path / "archive").mkdir()
    with sqlite3.connect(tmp_path / "archive" / "archive_2025.db") as conn:
        conn.execute(
            """
            CREATE TABLE prompt_logs_archive (
                id INTEGER, user_id INTEGER, class_id INTEGER, session_id INTEGER,
                raw_prompt TEXT NOT NULL, final_prompt TEXT NOT NULL, model TEXT NOT NULL,
                status TEXT NOT NULL, client_ip TEXT, created_at TEXT NOT NULL,
                archived_at TEXT NOT NULL, message_preview TEXT, messages_json TEXT,
                api_endpoint TEXT, response_preview TEXT, tier_name TEXT, tier_confidence REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO prompt_logs_archive(id, raw_prompt, final_prompt, model, status, created_at, archived_at)"
            " VALUES (999, 'already archived', 'already archived', 'fake-model', 'ok',"
            " '2025-01-01T00:00:00+00:00', '2025-02-01T00:00:00+00:00')"
        )

    assert _archive_two_logs_with_token_counts(tmp_path) == [
        ("already archived", 0, 0, 0),
        ("counted", 12, 30, 42),
        ("uncounted", 0, 0, 0),
    ]


def test_archive_prompt_logs_finishes_a_backlog_larger_than_one_batch(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "Active", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    context = repo.verify_api_key_context(key)
    assert context is not None
    for index in range(21):
        repo.log_prompt(context, f"old {index}", f"old {index}", "fake-model", "ok", None)
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = ?", ("2026-01-01T00:00:00+00:00",))

    result = repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), archive_after_days=15)

    assert result["archived"] == 21
    assert repo.list_prompt_logs(teacher["id"], klass["id"]) == []


def test_purge_archived_prompt_logs_deletes_by_created_at(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        prompt_logs=PromptLogSettings(archive_after_days=15, delete_after_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "Active", None)
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
    ended = repo.create_class(teacher["id"], "Ended", None)
    session = repo.create_class_session(ended["id"], teacher["id"], "Session")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    context = repo.verify_api_key_context(key)
    assert context is not None
    repo.log_prompt(context, "ended log", "ended log", "fake-model", "ok", None)
    repo.set_class_status(ended["id"], "ended")
    with repo._connect() as conn:
        conn.execute(
            "UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?",
            ("2026-05-01T00:00:00+00:00", "ended log"),
        )
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
    klass = repo.create_class(teacher["id"], "Class", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    key_a = repo.redeem_invite(session["invite_code"], user_a["id"])["api_key"]
    key_b = repo.redeem_invite(session["invite_code"], user_b["id"])["api_key"]
    ctx_a = repo.verify_api_key_context(key_a)
    ctx_b = repo.verify_api_key_context(key_b)
    assert ctx_a is not None and ctx_b is not None
    repo.log_prompt(ctx_a, "a-live", "a-live", "fake-model", "ok", None)
    repo.log_prompt(ctx_b, "b-live", "b-live", "fake-model", "ok", None)
    repo.set_class_status(klass["id"], "ended")
    with repo._connect() as conn:
        conn.execute("UPDATE prompt_logs SET created_at = ?", ("2026-05-01T00:00:00+00:00",))
    assert repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC))["archived"] == 2

    # new class for fresh live logs after archive
    live_class = repo.create_class(teacher["id"], "Live", None)
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

    assert repo.delete_prompt_logs_for_users([]) == {"deleted_live": 0, "deleted_archive": 0, "deleted_token_usage": 0}
    result = repo.delete_prompt_logs_for_users([user_a["id"]])
    assert result == {"deleted_live": 1, "deleted_archive": 1, "deleted_token_usage": 0}

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
    klass = repo.create_class(teacher["id"], "AI", None)
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
    klass = repo.create_class(teacher["id"], "AI", None)
    session_at = datetime(2026, 6, 21, 14, 0, tzinfo=UTC).isoformat()
    session = repo.create_class_session(
        klass["id"],
        teacher["id"],
        "第一堂",
        session_at=session_at,
        expires_at=datetime(2026, 6, 21, 17, 0, tzinfo=UTC).isoformat(),
    )
    assert session["session_at"] == session_at
    assert session["name"] == "第一堂"
    assert session["expires_at"] == datetime(2026, 6, 21, 17, 0, tzinfo=UTC).isoformat()


def _class_with_session_starting_at(tmp_path, session_at: datetime):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None)
    session = repo.create_class_session(
        klass["id"], teacher["id"], "第一堂",
        session_at=session_at.isoformat(),
        expires_at=(session_at + timedelta(hours=3)).isoformat(),
    )
    return repo, session


def test_classroom_api_key_is_not_started_before_session_at(tmp_path):
    repo, session = _class_with_session_starting_at(tmp_path, datetime.now(UTC) - timedelta(minutes=5))
    student = repo.upsert_google_user("student@example.com", "Student")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    with repo._connect() as conn:
        conn.execute(
            "UPDATE class_sessions SET session_at = ? WHERE id = ?",
            ((datetime.now(UTC) + timedelta(hours=1)).isoformat(), session["id"]),
        )

    assert repo.verify_api_key_with_reason(key) == (None, "not_started")
    assert repo.verify_api_key_context(key) is None


def test_issued_classroom_api_key_follows_the_edited_session_window(tmp_path):
    start = datetime.now(UTC) - timedelta(minutes=5)
    repo, session = _class_with_session_starting_at(tmp_path, start)
    student = repo.upsert_google_user("student@example.com", "Student")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]
    later_than_old_end = start + timedelta(hours=4)

    repo.update_class_session(
        session["class_id"], session["id"], expires_at=(start + timedelta(hours=6)).isoformat()
    )
    assert repo.verify_api_key_with_reason(key, now=later_than_old_end)[1] is None

    repo.update_class_session(
        session["class_id"], session["id"], session_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat()
    )
    assert repo.verify_api_key_with_reason(key) == (None, "not_started")


def test_personal_api_key_replaced_by_a_newer_one_is_invalid(tmp_path):
    repo, _ = _class_with_session_starting_at(tmp_path, datetime.now(UTC) - timedelta(minutes=5))
    teacher = repo.get_user_by_email("teacher@example.com")
    old_key = repo.issue_long_lived_key(teacher["id"])
    new_key = repo.issue_long_lived_key(teacher["id"])

    assert repo.verify_api_key_with_reason(old_key) == (None, "invalid")
    assert repo.verify_api_key_with_reason(new_key)[1] is None


def test_personal_api_key_of_a_disabled_user_is_disabled(tmp_path):
    repo, _ = _class_with_session_starting_at(tmp_path, datetime.now(UTC) - timedelta(minutes=5))
    teacher = repo.get_user_by_email("teacher@example.com")
    key = repo.issue_long_lived_key(teacher["id"])
    repo.update_user(teacher["id"], status="inactive")

    assert repo.verify_api_key_with_reason(key) == (None, "disabled")


def test_invite_cannot_be_redeemed_before_session_at(tmp_path):
    repo, session = _class_with_session_starting_at(tmp_path, datetime.now(UTC) + timedelta(hours=1))
    student = repo.upsert_google_user("student@example.com", "Student")

    with pytest.raises(ValueError, match="尚未開始"):
        repo.redeem_invite(session["invite_code"], student["id"])
    with pytest.raises(ValueError, match="尚未開始"):
        repo.redeem_invite_with_nickname(session["invite_code"], "小明")


def test_classroom_api_key_works_once_session_at_has_passed(tmp_path):
    repo, session = _class_with_session_starting_at(tmp_path, datetime.now(UTC) - timedelta(minutes=1))
    student = repo.upsert_google_user("student@example.com", "Student")
    key = repo.redeem_invite(session["invite_code"], student["id"])["api_key"]

    context, failure = repo.verify_api_key_with_reason(key)
    assert failure is None
    assert context is not None


def test_create_session_requires_name(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None)
    with pytest.raises(ValueError, match="課堂名稱"):
        repo.create_class_session(klass["id"], teacher["id"], "   ")


def test_update_session_name(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None)
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
    klass = repo.create_class(teacher["id"], "AI", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    template = load_vans_template()
    assert session["session_chat_language_models"] == without_auto_tiers(template)
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
    klass = repo.create_class(teacher["id"], "AI Course", None)
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
    klass = repo.create_class(teacher["id"], "AI", None)
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
    klass = repo.create_class(teacher["id"], "AI", None)
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
    klass = repo.create_class(teacher["id"], "AI", None)
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


def test_agent_action_audit_accepts_a_target_outside_any_class_session(tmp_path):
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), _settings(tmp_path))
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")

    repo.record_agent_action_audit(
        actor_user_id=teacher["id"],
        action="release_key_quarantine",
        class_id=None,
        session_id=None,
        arguments={"provider": "ollama_cloud", "key_index": 0},
        invocation_channel="webmcp",
    )

    audits = repo.list_agent_action_audits()
    assert len(audits) == 1
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
    klass = repo.create_class(teacher["id"], "AI", None)
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


def _carries_auto_tiers(document) -> bool:
    return any(
        "autoTiers" in provider or any("autoTier" in model for model in provider.get("models", []))
        for provider in document
    )


def test_a_sitting_filled_from_the_starter_gets_no_auto_tiers(tmp_path):
    assert _carries_auto_tiers(load_vans_template()), "the starter ships default Auto Tiers"
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), _settings(tmp_path))
    owner = repo.upsert_google_user("owner@gmail.com", "Owner")
    klass = repo.create_class(owner["id"], "No template", None)
    repo.create_class_session(klass["id"], owner["id"], "Week 1")

    document = repo.list_class_sessions(klass["id"])[0]["session_chat_language_models"]

    assert template_model_ids(document) == template_model_ids(load_vans_template())
    assert not _carries_auto_tiers(document)


def _usage_world(repo):
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")
    klass = repo.create_class(teacher["id"], "Usage", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "Session")
    context = repo.verify_api_key_context(repo.redeem_invite(session["invite_code"], student["id"])["api_key"])
    assert context is not None
    return teacher, student, klass, context


def test_token_usage_is_recorded_queried_and_deleted_per_user(tmp_path):
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), _settings(tmp_path))
    teacher, student, klass, context = _usage_world(repo)
    repo.record_token_usage(context, "m", "/v1/chat/completions", 1, 2, 3)
    repo.record_token_usage(context, "m", "/v1/responses", 10, 20, 30)
    personal = context.__class__(user_id=student["id"], email=None, name=None)
    repo.record_token_usage(personal, "m", "/v1/chat/completions", 100, 100, 200)

    row = next(r for r in repo.class_usage(teacher["id"], klass["id"]) if r["user_id"] == student["id"])
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"], row["request_count"]) == (11, 22, 33, 2)

    assert repo.delete_prompt_logs_for_users([student["id"]])["deleted_token_usage"] == 3
    row = next(r for r in repo.class_usage(teacher["id"], klass["id"]) if r["user_id"] == student["id"])
    assert (row["total_tokens"], row["request_count"]) == (0, 0)


def _stored_last_used_at(repo, api_key_id: int) -> str | None:
    with repo._connect() as conn:
        row = conn.execute("SELECT last_used_at FROM api_keys WHERE id = ?", (api_key_id,)).fetchone()
    return row["last_used_at"]


def test_v1_check_writes_last_used_at_on_every_pass_while_the_key_check_waits_a_minute(tmp_path):
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "AI", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    api_key = repo.redeem_invite_with_nickname(session["invite_code"], "Ada")["api_key"]
    minute = timedelta(seconds=60)
    key_check_at = datetime.now(UTC) + timedelta(seconds=1)

    context, _ = repo.verify_api_key_with_reason(api_key, now=key_check_at, last_used_write_interval=minute)
    assert _stored_last_used_at(repo, context.api_key_id) == key_check_at.isoformat()
    repo.verify_api_key_with_reason(
        api_key, now=key_check_at + timedelta(seconds=10), last_used_write_interval=minute
    )
    assert _stored_last_used_at(repo, context.api_key_id) == key_check_at.isoformat()

    # `/v1/*` checks the same key a moment later, then again: each pass writes.
    for _ in range(2):
        written_a_second_ago = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        with repo._connect() as conn:
            conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?", (written_a_second_ago, context.api_key_id)
            )
        assert repo.verify_api_key_context(api_key) is not None
        assert _stored_last_used_at(repo, context.api_key_id) != written_a_second_ago


def test_a_fresh_database_has_exactly_the_snapshot_columns(tmp_path):
    settings = _settings(tmp_path)
    SqliteRouterRepository(settings.database.path, settings)

    with sqlite3.connect(settings.database.path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        columns = {
            table: frozenset(row[1] for row in conn.execute(f"PRAGMA table_info({table})"))
            for table in tables
        }

    # SQLite archives Prompt Logs in yearly files, so prompt_logs_archive is Postgres only.
    assert columns == SHARED_TABLE_COLUMNS
