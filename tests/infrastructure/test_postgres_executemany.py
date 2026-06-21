from unittest.mock import MagicMock

from src.infrastructure.config import RouterSettings
from src.infrastructure.repositories.postgres_router_repository import PostgresRouterRepository


def test_postgres_set_roles_uses_cursor_executemany():
    repo = PostgresRouterRepository.__new__(PostgresRouterRepository)
    repo.settings = RouterSettings()
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    repo._set_roles(conn, 1, ("admin", "teacher", "student"))

    conn.cursor.assert_called_once()
    cursor.executemany.assert_called_once()
    assert conn.executemany.call_count == 0
