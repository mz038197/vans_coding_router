from datetime import UTC, datetime, timedelta
import sqlite3

from src.infrastructure.config import AuthSettings, DatabaseSettings, PromptLogSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository


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
    session = repo.create_class_session(klass["id"], teacher["id"])
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
    session = repo.create_class_session(klass["id"], teacher["id"])
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
        prompt_logs=PromptLogSettings(retention_days=30),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    student = repo.upsert_google_user("student@example.com", "Student")

    active = repo.create_class(teacher["id"], "Active", None, 2)
    ended = repo.create_class(teacher["id"], "Ended", None, 2)
    repo.set_class_status(ended["id"], "ended")
    active_session = repo.create_class_session(active["id"], teacher["id"])
    repo.set_class_status(ended["id"], "active")
    ended_session = repo.create_class_session(ended["id"], teacher["id"])
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
        conn.execute("UPDATE prompt_logs SET created_at = ? WHERE raw_prompt = ?", ("2026-06-01T00:00:00+00:00", "recent active"))

    result = repo.archive_prompt_logs(now=datetime(2026, 6, 18, tzinfo=UTC), retention_days=30)

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
