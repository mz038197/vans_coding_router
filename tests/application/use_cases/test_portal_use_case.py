from datetime import UTC, datetime

import pytest

from src.application.use_cases.portal_use_case import PortalUseCase
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

    assert logs == []


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
