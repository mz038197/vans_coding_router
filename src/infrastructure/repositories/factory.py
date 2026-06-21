from __future__ import annotations

from src.domain.ports.router_repository import RouterRepositoryPort
from src.infrastructure.config import RouterSettings
from src.infrastructure.repositories.postgres_router_repository import PostgresRouterRepository
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository


def build_router_repository(settings: RouterSettings) -> RouterRepositoryPort:
    if settings.database.url:
        return PostgresRouterRepository(settings.database.url, settings)
    return SqliteRouterRepository(settings.database.path, settings)
