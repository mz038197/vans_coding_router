from datetime import UTC, datetime
import json

import pytest

from src.application.use_cases.portal_use_case import PortalUseCase
from src.domain.entities.auth import AuthContext
from src.infrastructure.config import DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository


def test_prompt_logs_passes_time_range_filters(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)

    logs = use_case.prompt_logs(
        teacher_id=teacher["id"],
        class_id=klass["id"],
        session_id=None,
        keyword=None,
        start_at="2026-01-01T00:00:00+00:00",
        end_at="2026-01-31T23:59:59+00:00",
    )

    assert logs == {"items": [], "limit": 100, "has_filter": True}


def test_prompt_logs_default_limit_without_filters(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    auth = AuthContext(user_id=teacher["id"], email=teacher["email"], name=teacher["name"], class_id=klass["id"])

    for idx in range(12):
        repo.log_prompt(
            auth=auth,
            raw_prompt=f"user: item-{idx}",
            final_prompt=f"user: item-{idx}",
            model="test-model",
            status="ok",
            client_ip="127.0.0.1",
            message_preview=f"preview-{idx}",
            messages_json=json.dumps([{"role": "user", "content": f"item-{idx}"}]),
        )

    logs = use_case.prompt_logs(
        teacher_id=teacher["id"],
        class_id=klass["id"],
        session_id=None,
        keyword=None,
    )

    assert logs["limit"] == 10
    assert logs["has_filter"] is False
    assert len(logs["items"]) == 10
    assert logs["items"][0]["message_preview"] == "preview-11"
    assert "raw_prompt" not in logs["items"][0]


def test_prompt_log_detail_returns_messages(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)
    auth = AuthContext(user_id=teacher["id"], email=teacher["email"], name=teacher["name"], class_id=klass["id"])
    repo.log_prompt(
        auth=auth,
        raw_prompt="ignored",
        final_prompt="ignored",
        model="test-model",
        status="ok",
        client_ip="127.0.0.1",
        message_preview="學生問題",
        messages_json=json.dumps([{"role": "user", "content": "學生問題"}]),
    )
    log_id = repo.list_prompt_logs(teacher["id"], klass["id"], limit=1)[0]["id"]

    detail = use_case.prompt_log_detail(teacher["id"], klass["id"], log_id)

    assert detail == {
        "messages": [{"role": "user", "content": "學生問題"}],
        "api_endpoint": "",
        "response_preview": "",
    }


def test_prompt_log_detail_requires_class_owner(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    other = repo.upsert_google_user("other@example.com", "Other")
    repo.update_user(teacher["id"], role="teacher")
    repo.update_user(other["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)

    with pytest.raises(PermissionError):
        use_case.prompt_log_detail(other["id"], klass["id"], 1)


def test_archive_prompt_logs_delegates_to_repository(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")

    result = use_case.admin_run_archive(admin["id"], now=datetime(2026, 6, 18, tzinfo=UTC))

    assert result == {"archived": 0}


def test_admin_run_archive_requires_admin(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")

    with pytest.raises(PermissionError):
        use_case.admin_run_archive(teacher["id"])


def test_admin_can_update_non_secret_settings_file(tmp_path):
    config_path = tmp_path / "router.yaml"
    config_path.write_text(
        "student_default_ttl_hours: 2\n"
        "auth:\n"
        "  open_registration: true\n"
        "database:\n"
        f"  path: {tmp_path / 'router.db'}\n"
        f"  archive_dir: {tmp_path / 'archive'}\n"
        "prompt_logs:\n"
        "  retention_days: 30\n",
        encoding="utf-8",
    )
    settings = RouterSettings(
        path=str(config_path),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")

    summary = use_case.admin_update_settings(
        admin["id"],
        retention_days=14,
        student_default_ttl_hours=3,
        open_registration=False,
    )

    text = config_path.read_text(encoding="utf-8")
    assert "retention_days: 14" in text
    assert "student_default_ttl_hours: 3" in text
    assert "open_registration: false" in text
    assert summary["prompt_logs"]["retention_days"] == 14
    assert summary["student_default_ttl_hours"] == 3
    assert summary["auth"]["open_registration"] is False


def test_admin_can_disable_class(tmp_path):
    settings = RouterSettings(database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")))
    repo = SqliteRouterRepository(str(tmp_path / "router.db"), settings)
    use_case = PortalUseCase(repo, settings)
    admin = repo.upsert_google_user("admin@example.com", "Admin")
    repo.update_user(admin["id"], role="admin")
    teacher = repo.upsert_google_user("teacher@example.com", "Teacher")
    repo.update_user(teacher["id"], role="teacher")
    klass = repo.create_class(teacher["id"], "AI", None, 2)

    updated = use_case.admin_update_class(admin["id"], klass["id"], status="ended")

    assert updated is not None
    assert updated["status"] == "ended"
