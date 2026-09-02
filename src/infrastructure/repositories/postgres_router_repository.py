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
                    classroom_nickname TEXT,
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
            self._backfill_ended_session_expires(conn)
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
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS speech_transcription_enabled BOOLEAN NOT NULL DEFAULT FALSE"
            )
            conn.execute(
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS prompt_logging_enabled BOOLEAN NOT NULL DEFAULT TRUE"
            )
            conn.execute(
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS course_catalog_yaml TEXT NOT NULL DEFAULT 'actions: []\n'"
            )
            conn.execute(
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS seat_limit INTEGER NOT NULL DEFAULT 60"
            )
            conn.execute(
                "ALTER TABLE class_sessions ADD COLUMN IF NOT EXISTS model_allowlist_json TEXT"
            )
            conn.execute("ALTER TABLE class_members ADD COLUMN IF NOT EXISTS classroom_nickname TEXT")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS class_members_classroom_nickname
                ON class_members(class_id, classroom_nickname)
                WHERE classroom_nickname IS NOT NULL
                """
            )
            conn.commit()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_sessions (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    token_hash TEXT NOT NULL UNIQUE,
                    browser_description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    absolute_expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revoked_by INTEGER REFERENCES users(id),
                    revocation_reason TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS portal_sessions_user_id ON portal_sessions(user_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_session_events (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    session_id INTEGER REFERENCES portal_sessions(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    actor_user_id INTEGER REFERENCES users(id),
                    occurred_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS portal_session_events_user_id ON portal_session_events(user_id)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_action_audits (
                    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    actor_user_id INTEGER NOT NULL REFERENCES users(id),
                    action TEXT NOT NULL,
                    class_id INTEGER REFERENCES classes(id),
                    session_id INTEGER REFERENCES class_sessions(id),
                    arguments_json TEXT NOT NULL,
                    invocation_channel TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS agent_action_audits_actor_user_id ON agent_action_audits(actor_user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS agent_action_audits_target ON agent_action_audits(class_id, session_id)"
            )
            conn.execute(
                "ALTER TABLE agent_action_audits ALTER COLUMN class_id DROP NOT NULL"
            )
            conn.execute(
                "ALTER TABLE agent_action_audits ALTER COLUMN session_id DROP NOT NULL"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extension_handoff_nonces (
                    nonce TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
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

    def _purge_archived_before(self, cutoff: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                self._sql("DELETE FROM prompt_logs_archive WHERE created_at < ?"),
                (cutoff,),
            )
            return int(cur.rowcount or 0)

    def _clear_all_archived(self) -> int:
        with self._connect() as conn:
            count = conn.execute(self._sql("SELECT COUNT(*) AS n FROM prompt_logs_archive")).fetchone()["n"]
            conn.execute(self._sql("DELETE FROM prompt_logs_archive"))
            return int(count)

    def _archived_counts_by_user(self) -> dict[int, int]:
        with self._connect() as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT user_id, COUNT(*) AS cnt
                    FROM prompt_logs_archive
                    WHERE user_id IS NOT NULL
                    GROUP BY user_id
                    """
                )
            ).fetchall()
        return {int(row["user_id"]): int(row["cnt"]) for row in rows}

    def _delete_archived_for_users(self, user_ids: list[int]) -> int:
        if not user_ids:
            return 0
        placeholders = ", ".join("?" for _ in user_ids)
        with self._connect() as conn:
            cur = conn.execute(
                self._sql(f"DELETE FROM prompt_logs_archive WHERE user_id IN ({placeholders})"),
                tuple(user_ids),
            )
            return int(cur.rowcount or 0)
