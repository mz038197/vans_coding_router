from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from src.infrastructure.config import RouterSettings
from src.infrastructure.repositories.router_repository_base import RouterRepositoryBase
from src.infrastructure.repositories.router_repository_helpers import dt


class SqliteRouterRepository(RouterRepositoryBase):
    def __init__(self, db_path: str, settings: RouterSettings):
        self.db_path = str(Path(db_path).expanduser())
        super().__init__(settings)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @property
    def dialect(self) -> str:
        return "sqlite"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    google_sub TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, role)
                );
                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    teacher_id INTEGER NOT NULL REFERENCES users(id),
                    api_key_ttl_hours INTEGER NOT NULL DEFAULT 2,
                    status TEXT NOT NULL DEFAULT 'active',
                    ends_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS class_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL REFERENCES classes(id),
                    invite_code TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    session_at TEXT,
                    name TEXT
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    session_id INTEGER REFERENCES class_sessions(id),
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    expires_at TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS session_redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    redeemed_at TEXT NOT NULL,
                    UNIQUE(session_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS class_members (
                    class_id INTEGER NOT NULL REFERENCES classes(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL DEFAULT 'student',
                    status TEXT NOT NULL DEFAULT 'active',
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY(class_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS prompt_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    class_id INTEGER REFERENCES classes(id),
                    session_id INTEGER REFERENCES class_sessions(id),
                    raw_prompt TEXT NOT NULL,
                    final_prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    client_ip TEXT,
                    created_at TEXT NOT NULL,
                    message_preview TEXT,
                    messages_json TEXT
                );
                """
            )
            self._ensure_column(conn, "prompt_logs", "prompt_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "prompt_logs", "completion_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "prompt_logs", "total_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "prompt_logs", "message_preview", "TEXT")
            self._ensure_column(conn, "prompt_logs", "messages_json", "TEXT")
            self._ensure_column(conn, "prompt_logs", "api_endpoint", "TEXT")
            self._ensure_column(conn, "prompt_logs", "response_preview", "TEXT")
            self._ensure_column(conn, "class_sessions", "session_at", "TEXT")
            self._ensure_column(conn, "class_sessions", "name", "TEXT")
            self._ensure_column(
                conn,
                "class_sessions",
                "image_generation_enabled",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._backfill_user_roles(conn)

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _archive_row(self, row: dict[str, Any], archived_at: datetime) -> None:
        from src.infrastructure.repositories.router_repository_helpers import parse_dt

        created = parse_dt(row["created_at"]) or archived_at
        archive_dir = Path(self.settings.database.archive_dir).expanduser()
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"archive_{created.year}.db"
        with sqlite3.connect(archive_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_logs_archive (
                    id INTEGER,
                    user_id INTEGER,
                    class_id INTEGER,
                    session_id INTEGER,
                    raw_prompt TEXT NOT NULL,
                    final_prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    client_ip TEXT,
                    created_at TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    message_preview TEXT,
                    messages_json TEXT
                )
                """
            )
            self._ensure_column(conn, "prompt_logs_archive", "message_preview", "TEXT")
            self._ensure_column(conn, "prompt_logs_archive", "messages_json", "TEXT")
            self._ensure_column(conn, "prompt_logs_archive", "api_endpoint", "TEXT")
            self._ensure_column(conn, "prompt_logs_archive", "response_preview", "TEXT")
            conn.execute(
                """
                INSERT INTO prompt_logs_archive(
                    id, user_id, class_id, session_id, raw_prompt, final_prompt, model, status,
                    client_ip, created_at, archived_at, message_preview, messages_json,
                    api_endpoint, response_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["user_id"],
                    row["class_id"],
                    row["session_id"],
                    row["raw_prompt"],
                    row["final_prompt"],
                    row["model"],
                    row["status"],
                    row["client_ip"],
                    row["created_at"],
                    dt(archived_at),
                    row.get("message_preview") or "",
                    row.get("messages_json") or "",
                    row.get("api_endpoint") or "",
                    row.get("response_preview") or "",
                ),
            )
            conn.commit()

    def _after_archive(self, archived_count: int) -> None:
        if archived_count <= 0:
            return
        with sqlite3.connect(self.db_path, isolation_level=None) as conn:
            conn.execute("VACUUM")
