from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from src.infrastructure.config import RouterSettings
from src.infrastructure.repositories.router_repository_base import RouterRepositoryBase
from src.infrastructure.repositories.router_repository_helpers import dt


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


class PostgresRouterRepository(RouterRepositoryBase):
    def __init__(self, database_url: str, settings: RouterSettings):
        self.database_url = _normalize_database_url(database_url)
        super().__init__(settings)
        self._init_schema()

    @property
    def dialect(self) -> str:
        return "postgres"

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    google_sub TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, role)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    name TEXT NOT NULL,
                    teacher_id INTEGER NOT NULL REFERENCES users(id),
                    api_key_ttl_hours INTEGER NOT NULL DEFAULT 2,
                    status TEXT NOT NULL DEFAULT 'active',
                    ends_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS class_sessions (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    class_id INTEGER NOT NULL REFERENCES classes(id),
                    invite_code TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    session_at TEXT,
                    name TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    session_id INTEGER REFERENCES class_sessions(id),
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    expires_at TEXT,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_redemptions (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES class_sessions(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    redeemed_at TEXT NOT NULL,
                    UNIQUE(session_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS class_members (
                    class_id INTEGER NOT NULL REFERENCES classes(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL DEFAULT 'student',
                    status TEXT NOT NULL DEFAULT 'active',
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY(class_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_logs (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
                )
                """
            )
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
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    client_ip TEXT,
                    created_at TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    message_preview TEXT,
                    messages_json TEXT
                )
                """
            )
            self._backfill_user_roles(conn)
            for table in ("prompt_logs", "prompt_logs_archive"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS api_endpoint TEXT")
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS response_preview TEXT")
            conn.execute(
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS image_generation_enabled BOOLEAN NOT NULL DEFAULT TRUE"
            )
            conn.execute(
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS tts_enabled BOOLEAN NOT NULL DEFAULT TRUE"
            )
            conn.execute(
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS prompt_logging_enabled BOOLEAN NOT NULL DEFAULT TRUE"
            )
            conn.commit()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _archive_row(self, row: dict[str, Any], archived_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                self._sql(
                    """
                    INSERT INTO prompt_logs_archive(
                        id, user_id, class_id, session_id, raw_prompt, final_prompt, model, status,
                        prompt_tokens, completion_tokens, total_tokens, client_ip, created_at, archived_at,
                        message_preview, messages_json, api_endpoint, response_preview
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    row["id"],
                    row["user_id"],
                    row["class_id"],
                    row["session_id"],
                    row["raw_prompt"],
                    row["final_prompt"],
                    row["model"],
                    row["status"],
                    row.get("prompt_tokens") or 0,
                    row.get("completion_tokens") or 0,
                    row.get("total_tokens") or 0,
                    row["client_ip"],
                    row["created_at"],
                    dt(archived_at),
                    row.get("message_preview") or "",
                    row.get("messages_json") or "",
                    row.get("api_endpoint") or "",
                    row.get("response_preview") or "",
                ),
            )
