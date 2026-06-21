from src.infrastructure.config import DatabaseSettings, RouterSettings
from src.infrastructure.repositories.factory import build_router_repository
from src.infrastructure.repositories.postgres_router_repository import PostgresRouterRepository
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository


def test_build_router_repository_uses_sqlite_without_database_url(tmp_path):
    settings = RouterSettings(
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
    )
    repo = build_router_repository(settings)
    assert isinstance(repo, SqliteRouterRepository)


def test_build_router_repository_uses_postgres_when_database_url_is_set(monkeypatch):
    monkeypatch.setattr(PostgresRouterRepository, "_init_schema", lambda self: None)
    settings = RouterSettings(database=DatabaseSettings(url="postgresql://vcr:vcr@localhost:5432/vans_coding_router"))
    repo = build_router_repository(settings)
    assert isinstance(repo, PostgresRouterRepository)
