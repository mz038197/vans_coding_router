from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
from typing import Any

from src.domain.entities.auth import AuthContext
from src.infrastructure.config import RouterSettings


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SqliteRouterRepository:
    def __init__(self, db_path: str, settings: RouterSettings):
        self.db_path = str(Path(db_path).expanduser())
        self.settings = settings
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

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
                    status TEXT NOT NULL DEFAULT 'active'
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
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "prompt_logs", "prompt_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "prompt_logs", "completion_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "prompt_logs", "total_tokens", "INTEGER NOT NULL DEFAULT 0")
            self._backfill_user_roles(conn)

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _backfill_user_roles(self, conn: sqlite3.Connection) -> None:
        now = _dt(_utc_now())
        rows = conn.execute("SELECT id, role FROM users").fetchall()
        for row in rows:
            roles = self._roles_for_legacy_role(row["role"])
            for role in roles:
                conn.execute(
                    "INSERT OR IGNORE INTO user_roles(user_id, role, granted_at) VALUES (?, ?, ?)",
                    (row["id"], role, now),
                )

    def is_enabled(self) -> bool:
        return True

    def _roles_for_legacy_role(self, role: str) -> tuple[str, ...]:
        if role == "admin":
            return ("admin", "teacher", "student")
        if role == "teacher":
            return ("teacher", "student")
        return ("student",)

    def _roles_for_email(self, email: str) -> tuple[str, ...]:
        normalized = email.lower()
        domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
        is_teacher = bool(self.settings.auth.teacher_domain and domain == self.settings.auth.teacher_domain)
        is_admin = normalized in self.settings.auth.admin_emails
        if is_admin:
            return ("admin", "teacher", "student")
        if is_teacher:
            return ("teacher", "student")
        return ("student",)

    def _primary_role(self, roles: tuple[str, ...]) -> str:
        for role in ("admin", "teacher", "student"):
            if role in roles:
                return role
        return "student"

    def _roles_for_user(self, conn: sqlite3.Connection, user_id: int) -> tuple[str, ...]:
        rows = conn.execute("SELECT role FROM user_roles WHERE user_id = ? ORDER BY role", (user_id,)).fetchall()
        roles = tuple(row["role"] for row in rows)
        if roles:
            return roles
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._roles_for_legacy_role(row["role"]) if row else ()

    def _with_roles(self, conn: sqlite3.Connection, user: dict[str, Any]) -> dict[str, Any]:
        roles = self._roles_for_user(conn, int(user["id"]))
        user["roles"] = list(roles)
        user["role"] = self._primary_role(roles)
        return user

    def _set_roles(self, conn: sqlite3.Connection, user_id: int, roles: list[str] | tuple[str, ...]) -> None:
        valid_roles = tuple(role for role in ("admin", "teacher", "student") if role in set(roles))
        if not valid_roles:
            valid_roles = ("student",)
        now = _dt(_utc_now())
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO user_roles(user_id, role, granted_at) VALUES (?, ?, ?)",
            [(user_id, role, now) for role in valid_roles],
        )
        conn.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (self._primary_role(valid_roles), now, user_id),
        )

    def upsert_google_user(self, email: str, name: str, google_sub: str | None = None) -> dict[str, Any]:
        roles = self._roles_for_email(email)
        role = self._primary_role(roles)
        now = _dt(_utc_now())
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE users SET name = ?, google_sub = COALESCE(?, google_sub), updated_at = ? WHERE id = ?",
                    (name, google_sub, now, existing["id"]),
                )
                if email.lower() in self.settings.auth.admin_emails:
                    self._set_roles(conn, int(existing["id"]), roles)
            else:
                cur = conn.execute(
                    "INSERT INTO users(email, name, role, status, google_sub, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?, ?)",
                    (email.lower(), name, role, google_sub, now, now),
                )
                self._set_roles(conn, int(cur.lastrowid), roles)
            return self._with_roles(conn, dict(conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()))

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._with_roles(conn, dict(row)) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
            return self._with_roles(conn, dict(row)) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, email, name, role, status, created_at FROM users ORDER BY created_at DESC").fetchall()
            return [self._with_roles(conn, dict(row)) for row in rows]

    def update_user(self, user_id: int, role: str | None = None, status: str | None = None, roles: list[str] | None = None) -> dict[str, Any] | None:
        fields = []
        values: list[Any] = []
        if role:
            fields.append("role = ?")
            values.append(role)
        if status:
            fields.append("status = ?")
            values.append(status)
        if not fields and roles is None:
            return self.get_user(user_id)
        with self._connect() as conn:
            if fields:
                fields.append("updated_at = ?")
                values.append(_dt(_utc_now()))
                values.append(user_id)
                conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
            if roles is not None:
                self._set_roles(conn, user_id, roles)
            elif role:
                self._set_roles(conn, user_id, self._roles_for_legacy_role(role))
        return self.get_user(user_id)

    def _hash_key(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def _make_key(self, *parts: object) -> str:
        payload = ":".join(str(p) for p in parts)
        digest = hmac.new(
            self.settings.auth.session_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return "vcr_sk_" + digest

    def verify_api_key(self, api_key: str) -> tuple[bool, str | None]:
        context = self.verify_api_key_context(api_key)
        return (context is not None, context.teacher_name if context else None)

    def verify_api_key_context(self, api_key: str) -> AuthContext | None:
        if not api_key:
            return None
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT k.*, u.email, u.name, u.role, u.status AS user_status,
                       s.class_id, s.expires_at AS session_expires_at, s.status AS session_status,
                       c.status AS class_status, c.ends_at AS class_ends_at
                FROM api_keys k
                JOIN users u ON u.id = k.user_id
                LEFT JOIN class_sessions s ON s.id = k.session_id
                LEFT JOIN classes c ON c.id = s.class_id
                WHERE k.key_hash = ?
                """,
                (self._hash_key(api_key),),
            ).fetchone()
            if not row or not row["enabled"] or row["user_status"] != "active":
                return None
            expires_at = _parse_dt(row["expires_at"])
            session_expires_at = _parse_dt(row["session_expires_at"])
            class_ends_at = _parse_dt(row["class_ends_at"])
            if expires_at and now >= expires_at:
                return None
            if row["session_id"] and (row["session_status"] != "active" or (session_expires_at and now >= session_expires_at)):
                return None
            if row["session_id"] and (row["class_status"] != "active" or (class_ends_at and now >= class_ends_at)):
                return None
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (_dt(now), row["id"]))
            roles = self._roles_for_user(conn, int(row["user_id"]))
            return AuthContext(
                user_id=row["user_id"],
                email=row["email"],
                name=row["name"],
                role=self._primary_role(roles),
                roles=roles,
                is_admin="admin" in roles,
                api_key_id=row["id"],
                session_id=row["session_id"],
                class_id=row["class_id"],
                key_prefix=row["key_prefix"],
            )

    def issue_long_lived_key(self, user_id: int) -> str:
        raw = "vcr_sk_" + secrets.token_hex(32)
        now = _dt(_utc_now())
        with self._connect() as conn:
            conn.execute("UPDATE api_keys SET enabled = 0 WHERE user_id = ? AND session_id IS NULL", (user_id,))
            conn.execute(
                "INSERT INTO api_keys(user_id, key_hash, key_prefix, created_at) VALUES (?, ?, ?, ?)",
                (user_id, self._hash_key(raw), raw[:14], now),
            )
        return raw

    def issue_session_key(self, user_id: int, session_id: int) -> str:
        raw = self._make_key("session", session_id, user_id)
        now = _dt(_utc_now())
        with self._connect() as conn:
            session = conn.execute("SELECT expires_at FROM class_sessions WHERE id = ?", (session_id,)).fetchone()
            existing = conn.execute(
                "SELECT id FROM api_keys WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO api_keys(user_id, session_id, key_hash, key_prefix, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, session_id, self._hash_key(raw), raw[:14], session["expires_at"], now),
                )
        return raw

    def get_active_keys(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT k.id, k.key_prefix, k.expires_at, k.enabled, s.id AS session_id, c.name AS class_name
                FROM api_keys k
                LEFT JOIN class_sessions s ON s.id = k.session_id
                LEFT JOIN classes c ON c.id = s.class_id
                WHERE k.user_id = ? AND k.enabled = 1
                ORDER BY k.created_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_class(self, teacher_id: int, name: str, ends_at: str | None, api_key_ttl_hours: int | None = None) -> dict[str, Any]:
        now = _dt(_utc_now())
        ttl = api_key_ttl_hours or self.settings.student_default_ttl_hours
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO classes(name, teacher_id, api_key_ttl_hours, ends_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, teacher_id, ttl, ends_at, now, now),
            )
            return dict(conn.execute("SELECT * FROM classes WHERE id = ?", (cur.lastrowid,)).fetchone())

    def get_class(self, class_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
            return dict(row) if row else None

    def list_classes(self, teacher_id: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT c.*, u.name AS teacher_name, u.email AS teacher_email,
                   (SELECT COUNT(*) FROM class_members m WHERE m.class_id = c.id) AS member_count
            FROM classes c JOIN users u ON u.id = c.teacher_id
        """
        params: tuple[Any, ...] = ()
        if teacher_id is not None:
            sql += " WHERE c.teacher_id = ?"
            params = (teacher_id,)
        sql += " ORDER BY c.created_at DESC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def set_class_status(self, class_id: int, status: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE classes SET status = ?, updated_at = ? WHERE id = ?",
                (status, _dt(_utc_now()), class_id),
            )
        return self.get_class(class_id)

    def create_class_session(self, class_id: int, created_by: int, ttl_hours: int | None = None) -> dict[str, Any]:
        klass = self.get_class(class_id)
        if not klass or klass["status"] != "active":
            raise ValueError("class is not active")
        expires_at = _utc_now() + timedelta(hours=int(ttl_hours or klass["api_key_ttl_hours"]))
        invite_code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
        now = _dt(_utc_now())
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO class_sessions(class_id, invite_code, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (class_id, invite_code, _dt(expires_at), created_by, now),
            )
            return dict(conn.execute("SELECT * FROM class_sessions WHERE id = ?", (cur.lastrowid,)).fetchone())

    def update_class_session(self, class_id: int, session_id: int, expires_at: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM class_sessions WHERE id = ? AND class_id = ?",
                (session_id, class_id),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE class_sessions SET expires_at = ? WHERE id = ?",
                (expires_at, session_id),
            )
            conn.execute(
                "UPDATE api_keys SET expires_at = ? WHERE session_id = ?",
                (expires_at, session_id),
            )
            updated = conn.execute("SELECT * FROM class_sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(updated) if updated else None

    def redeem_invite(self, invite_code: str, user_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            session = conn.execute(
                """
                SELECT s.*, c.name AS class_name, c.status AS class_status
                FROM class_sessions s JOIN classes c ON c.id = s.class_id
                WHERE s.invite_code = ?
                """,
                (invite_code.strip().upper(),),
            ).fetchone()
            if not session or session["status"] != "active" or session["class_status"] != "active":
                raise ValueError("invalid invite")
            if _utc_now() >= _parse_dt(session["expires_at"]):
                raise ValueError("expired invite")
            now = _dt(_utc_now())
            conn.execute(
                "INSERT OR IGNORE INTO session_redemptions(session_id, user_id, redeemed_at) VALUES (?, ?, ?)",
                (session["id"], user_id, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO class_members(class_id, user_id, role, status, joined_at) VALUES (?, ?, 'student', 'active', ?)",
                (session["class_id"], user_id, now),
            )
        key = self.issue_session_key(user_id, int(session["id"]))
        return {"api_key": key, "session": dict(session)}

    def list_session_redemptions(self, class_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id AS session_id, s.invite_code, s.expires_at, r.redeemed_at, u.name, u.email
                FROM class_sessions s
                LEFT JOIN session_redemptions r ON r.session_id = s.id
                LEFT JOIN users u ON u.id = r.user_id
                WHERE s.class_id = ?
                ORDER BY s.created_at DESC, r.redeemed_at DESC
                """,
                (class_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def log_prompt(
        self,
        auth: AuthContext | None,
        raw_prompt: str,
        final_prompt: str,
        model: str,
        status: str,
        client_ip: str | None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_logs(
                    user_id, class_id, session_id, raw_prompt, final_prompt, model, status,
                    prompt_tokens, completion_tokens, total_tokens, client_ip, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    auth.user_id if auth else None,
                    auth.class_id if auth else None,
                    auth.session_id if auth else None,
                    raw_prompt,
                    final_prompt,
                    model,
                    status,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    client_ip,
                    _dt(_utc_now()),
                ),
            )

    def class_usage(self, teacher_id: int, class_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.id AS user_id, u.name, u.email,
                       COALESCE(SUM(l.prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(l.completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(l.total_tokens), 0) AS total_tokens
                FROM class_members m
                JOIN users u ON u.id = m.user_id
                JOIN classes c ON c.id = m.class_id
                LEFT JOIN prompt_logs l ON l.user_id = u.id AND l.class_id = m.class_id AND l.status = 'ok'
                WHERE m.class_id = ? AND c.teacher_id = ?
                GROUP BY u.id, u.name, u.email
                ORDER BY total_tokens DESC, u.name
                """,
                (class_id, teacher_id),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                sessions = conn.execute(
                    """
                    SELECT s.id AS session_id, s.invite_code,
                           COALESCE(SUM(l.prompt_tokens), 0) AS prompt_tokens,
                           COALESCE(SUM(l.completion_tokens), 0) AS completion_tokens,
                           COALESCE(SUM(l.total_tokens), 0) AS total_tokens
                    FROM class_sessions s
                    LEFT JOIN prompt_logs l ON l.session_id = s.id AND l.user_id = ? AND l.status = 'ok'
                    WHERE s.class_id = ?
                    GROUP BY s.id, s.invite_code
                    ORDER BY s.created_at DESC
                    """,
                    (item["user_id"], class_id),
                ).fetchall()
                item["sessions"] = [dict(session) for session in sessions]
                result.append(item)
            return result

    def list_prompt_logs(
        self,
        teacher_id: int,
        class_id: int,
        session_id: int | None = None,
        keyword: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [teacher_id, class_id]
        sql = """
            SELECT l.*, u.name AS user_name, u.email AS user_email
            FROM prompt_logs l
            JOIN classes c ON c.id = l.class_id
            LEFT JOIN users u ON u.id = l.user_id
            WHERE c.teacher_id = ? AND l.class_id = ?
        """
        if session_id is not None:
            sql += " AND l.session_id = ?"
            params.append(session_id)
        if keyword:
            sql += " AND (l.raw_prompt LIKE ? OR u.name LIKE ? OR u.email LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        if start_at:
            sql += " AND l.created_at >= ?"
            params.append(start_at)
        if end_at:
            sql += " AND l.created_at <= ?"
            params.append(end_at)
        sql += " ORDER BY l.created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def archive_prompt_logs(self, now: datetime | None = None, retention_days: int | None = None) -> dict[str, Any]:
        current = now or _utc_now()
        cutoff = current - timedelta(days=retention_days if retention_days is not None else self.settings.prompt_logs.retention_days)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.*
                FROM prompt_logs l
                LEFT JOIN classes c ON c.id = l.class_id
                WHERE c.status = 'ended' OR l.created_at < ?
                ORDER BY l.created_at
                """,
                (_dt(cutoff),),
            ).fetchall()
            for row in rows:
                self._archive_row(dict(row), current)
            if rows:
                conn.executemany("DELETE FROM prompt_logs WHERE id = ?", [(row["id"],) for row in rows])
        if rows:
            with sqlite3.connect(self.db_path, isolation_level=None) as vacuum_conn:
                vacuum_conn.execute("VACUUM")
        return {"archived": len(rows)}

    def _archive_row(self, row: dict[str, Any], archived_at: datetime) -> None:
        created = _parse_dt(row["created_at"]) or archived_at
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
                    archived_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO prompt_logs_archive(
                    id, user_id, class_id, session_id, raw_prompt, final_prompt, model, status, client_ip, created_at, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    _dt(archived_at),
                ),
            )
