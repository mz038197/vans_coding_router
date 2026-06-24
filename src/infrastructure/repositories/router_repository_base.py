from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Any, Iterator

from src.domain.entities.auth import AuthContext
from src.infrastructure.config import RouterSettings
from src.infrastructure.repositories.router_repository_helpers import dt, parse_dt, prompt_log_messages, utc_now


class RouterRepositoryBase(ABC):
    def __init__(self, settings: RouterSettings):
        self.settings = settings

    @property
    @abstractmethod
    def dialect(self) -> str:
        ...

    @abstractmethod
    @contextmanager
    def _connect(self) -> Iterator[Any]:
        ...

    @abstractmethod
    def _init_schema(self) -> None:
        ...

    @abstractmethod
    def _archive_row(self, row: dict[str, Any], archived_at: datetime) -> None:
        ...

    def _sql(self, query: str) -> str:
        if self.dialect == "postgres":
            return query.replace("?", "%s")
        return query

    def _disabled_enabled_value(self) -> int | bool:
        return False if self.dialect == "postgres" else 0

    def _executemany(self, conn: Any, query: str, params: list[tuple[Any, ...]]) -> None:
        sql = self._sql(query)
        if not params:
            return
        if self.dialect == "postgres":
            with conn.cursor() as cur:
                cur.executemany(sql, params)
            return
        conn.executemany(sql, params)

    def _insert_or_ignore_user_role(self, conn: Any, user_id: int, role: str, granted_at: str) -> None:
        if self.dialect == "postgres":
            conn.execute(
                self._sql(
                    "INSERT INTO user_roles(user_id, role, granted_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (user_id, role) DO NOTHING"
                ),
                (user_id, role, granted_at),
            )
            return
        conn.execute(
            self._sql("INSERT OR IGNORE INTO user_roles(user_id, role, granted_at) VALUES (?, ?, ?)"),
            (user_id, role, granted_at),
        )

    def _insert_or_ignore_redemption(self, conn: Any, session_id: int, user_id: int, redeemed_at: str) -> None:
        if self.dialect == "postgres":
            conn.execute(
                self._sql(
                    "INSERT INTO session_redemptions(session_id, user_id, redeemed_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (session_id, user_id) DO NOTHING"
                ),
                (session_id, user_id, redeemed_at),
            )
            return
        conn.execute(
            self._sql("INSERT OR IGNORE INTO session_redemptions(session_id, user_id, redeemed_at) VALUES (?, ?, ?)"),
            (session_id, user_id, redeemed_at),
        )

    def _insert_or_ignore_class_member(
        self,
        conn: Any,
        class_id: int,
        user_id: int,
        joined_at: str,
    ) -> None:
        if self.dialect == "postgres":
            conn.execute(
                self._sql(
                    "INSERT INTO class_members(class_id, user_id, role, status, joined_at) "
                    "VALUES (?, ?, 'student', 'active', ?) ON CONFLICT (class_id, user_id) DO NOTHING"
                ),
                (class_id, user_id, joined_at),
            )
            return
        conn.execute(
            self._sql(
                "INSERT OR IGNORE INTO class_members(class_id, user_id, role, status, joined_at) "
                "VALUES (?, ?, 'student', 'active', ?)"
            ),
            (class_id, user_id, joined_at),
        )

    def _insert_returning_id(self, conn: Any, query: str, params: tuple[Any, ...]) -> int:
        if self.dialect == "postgres":
            row = conn.execute(self._sql(query + " RETURNING id"), params).fetchone()
            return int(row["id"])
        cur = conn.execute(self._sql(query), params)
        return int(cur.lastrowid)

    def _backfill_user_roles(self, conn: Any) -> None:
        now = dt(utc_now())
        rows = conn.execute(self._sql("SELECT id, role FROM users")).fetchall()
        for row in rows:
            roles = self._roles_for_legacy_role(row["role"])
            for role in roles:
                self._insert_or_ignore_user_role(conn, int(row["id"]), role, now or "")

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

    def _roles_for_user(self, conn: Any, user_id: int) -> tuple[str, ...]:
        rows = conn.execute(
            self._sql("SELECT role FROM user_roles WHERE user_id = ? ORDER BY role"),
            (user_id,),
        ).fetchall()
        roles = tuple(row["role"] for row in rows)
        if roles:
            return roles
        row = conn.execute(self._sql("SELECT role FROM users WHERE id = ?"), (user_id,)).fetchone()
        return self._roles_for_legacy_role(row["role"]) if row else ()

    def _with_roles(self, conn: Any, user: dict[str, Any]) -> dict[str, Any]:
        roles = self._roles_for_user(conn, int(user["id"]))
        user["roles"] = list(roles)
        user["role"] = self._primary_role(roles)
        return user

    def _set_roles(self, conn: Any, user_id: int, roles: list[str] | tuple[str, ...]) -> None:
        valid_roles = tuple(role for role in ("admin", "teacher", "student") if role in set(roles))
        if not valid_roles:
            valid_roles = ("student",)
        now = dt(utc_now())
        conn.execute(self._sql("DELETE FROM user_roles WHERE user_id = ?"), (user_id,))
        self._executemany(
            conn,
            "INSERT INTO user_roles(user_id, role, granted_at) VALUES (?, ?, ?)",
            [(user_id, role, now) for role in valid_roles],
        )
        conn.execute(
            self._sql("UPDATE users SET role = ?, updated_at = ? WHERE id = ?"),
            (self._primary_role(valid_roles), now, user_id),
        )

    def upsert_google_user(self, email: str, name: str, google_sub: str | None = None) -> dict[str, Any]:
        roles = self._roles_for_email(email)
        role = self._primary_role(roles)
        now = dt(utc_now())
        with self._connect() as conn:
            existing = conn.execute(
                self._sql("SELECT * FROM users WHERE email = ?"),
                (email.lower(),),
            ).fetchone()
            if existing:
                conn.execute(
                    self._sql(
                        "UPDATE users SET name = ?, google_sub = COALESCE(?, google_sub), updated_at = ? WHERE id = ?"
                    ),
                    (name, google_sub, now, existing["id"]),
                )
                if email.lower() in self.settings.auth.admin_emails:
                    self._set_roles(conn, int(existing["id"]), roles)
            else:
                user_id = self._insert_returning_id(
                    conn,
                    "INSERT INTO users(email, name, role, status, google_sub, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'active', ?, ?, ?)",
                    (email.lower(), name, role, google_sub, now, now),
                )
                self._set_roles(conn, user_id, roles)
            row = conn.execute(
                self._sql("SELECT * FROM users WHERE email = ?"),
                (email.lower(),),
            ).fetchone()
            return self._with_roles(conn, dict(row))

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(self._sql("SELECT * FROM users WHERE id = ?"), (user_id,)).fetchone()
            return self._with_roles(conn, dict(row)) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(self._sql("SELECT * FROM users WHERE email = ?"), (email.lower(),)).fetchone()
            return self._with_roles(conn, dict(row)) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._sql("SELECT id, email, name, role, status, created_at FROM users ORDER BY created_at DESC")
            ).fetchall()
            return [self._with_roles(conn, dict(row)) for row in rows]

    def update_user(
        self,
        user_id: int,
        role: str | None = None,
        status: str | None = None,
        roles: list[str] | None = None,
    ) -> dict[str, Any] | None:
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
                values.append(dt(utc_now()))
                values.append(user_id)
                conn.execute(self._sql(f"UPDATE users SET {', '.join(fields)} WHERE id = ?"), values)
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

    def verify_api_key_with_reason(self, api_key: str) -> tuple[AuthContext | None, str | None]:
        from src.infrastructure.auth.client_api_key import normalize_api_key

        api_key = normalize_api_key(api_key)
        if not api_key:
            return None, "missing"
        now = utc_now()
        with self._connect() as conn:
            row = conn.execute(
                self._sql(
                    """
                    SELECT k.*, u.email, u.name, u.role, u.status AS user_status,
                           s.class_id, s.expires_at AS session_expires_at, s.status AS session_status,
                           c.status AS class_status, c.ends_at AS class_ends_at
                    FROM api_keys k
                    JOIN users u ON u.id = k.user_id
                    LEFT JOIN class_sessions s ON s.id = k.session_id
                    LEFT JOIN classes c ON c.id = s.class_id
                    WHERE k.key_hash = ?
                    """
                ),
                (self._hash_key(api_key),),
            ).fetchone()
            if not row:
                return None, "invalid"
            if not bool(row["enabled"]):
                return None, "disabled"
            if row["user_status"] != "active":
                return None, "disabled"
            expires_at = parse_dt(row["expires_at"])
            session_expires_at = parse_dt(row["session_expires_at"])
            class_ends_at = parse_dt(row["class_ends_at"])
            if expires_at and now >= expires_at:
                return None, "expired"
            if row["session_id"] and (
                row["session_status"] != "active" or (session_expires_at and now >= session_expires_at)
            ):
                return None, "expired"
            if row["session_id"] and (
                row["class_status"] != "active" or (class_ends_at and now >= class_ends_at)
            ):
                return None, "expired"
            conn.execute(
                self._sql("UPDATE api_keys SET last_used_at = ? WHERE id = ?"),
                (dt(now), row["id"]),
            )
            roles = self._roles_for_user(conn, int(row["user_id"]))
            return (
                AuthContext(
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
                ),
                None,
            )

    def verify_api_key_context(self, api_key: str) -> AuthContext | None:
        context, _ = self.verify_api_key_with_reason(api_key)
        return context

    def issue_long_lived_key(self, user_id: int) -> str:
        raw = "vcr_sk_" + secrets.token_hex(32)
        now = dt(utc_now())
        with self._connect() as conn:
            conn.execute(
                self._sql("UPDATE api_keys SET enabled = ? WHERE user_id = ? AND session_id IS NULL"),
                (self._disabled_enabled_value(), user_id),
            )
            conn.execute(
                self._sql("INSERT INTO api_keys(user_id, key_hash, key_prefix, created_at) VALUES (?, ?, ?, ?)"),
                (user_id, self._hash_key(raw), raw[:14], now),
            )
        return raw

    def issue_session_key(self, user_id: int, session_id: int) -> str:
        raw = self._make_key("session", session_id, user_id)
        now = dt(utc_now())
        key_hash = self._hash_key(raw)
        enabled = True if self.dialect == "postgres" else 1
        with self._connect() as conn:
            session = conn.execute(
                self._sql("SELECT expires_at FROM class_sessions WHERE id = ?"),
                (session_id,),
            ).fetchone()
            if session is None:
                raise ValueError("session not found")
            existing = conn.execute(
                self._sql("SELECT id FROM api_keys WHERE user_id = ? AND session_id = ?"),
                (user_id, session_id),
            ).fetchone()
            if existing:
                conn.execute(
                    self._sql(
                        "UPDATE api_keys SET key_hash = ?, key_prefix = ?, expires_at = ?, enabled = ? "
                        "WHERE id = ?"
                    ),
                    (key_hash, raw[:14], session["expires_at"], enabled, existing["id"]),
                )
            else:
                conn.execute(
                    self._sql(
                        "INSERT INTO api_keys(user_id, session_id, key_hash, key_prefix, expires_at, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)"
                    ),
                    (user_id, session_id, key_hash, raw[:14], session["expires_at"], now),
                )
        return raw

    def get_active_keys(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT k.id, k.key_prefix, k.expires_at, k.enabled, s.id AS session_id,
                           c.name AS class_name, s.name AS session_name, s.session_at
                    FROM api_keys k
                    LEFT JOIN class_sessions s ON s.id = k.session_id
                    LEFT JOIN classes c ON c.id = s.class_id
                    WHERE k.user_id = ? AND k.enabled = ?
                    ORDER BY k.created_at DESC
                    """
                ),
                (user_id, True if self.dialect == "postgres" else 1),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_class(
        self,
        teacher_id: int,
        name: str,
        ends_at: str | None,
        api_key_ttl_hours: int | None = None,
    ) -> dict[str, Any]:
        now = dt(utc_now())
        ttl = api_key_ttl_hours or self.settings.student_default_ttl_hours
        with self._connect() as conn:
            class_id = self._insert_returning_id(
                conn,
                "INSERT INTO classes(name, teacher_id, api_key_ttl_hours, ends_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, teacher_id, ttl, ends_at, now, now),
            )
            row = conn.execute(self._sql("SELECT * FROM classes WHERE id = ?"), (class_id,)).fetchone()
            return dict(row)

    def get_class(self, class_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(self._sql("SELECT * FROM classes WHERE id = ?"), (class_id,)).fetchone()
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
            return [dict(row) for row in conn.execute(self._sql(sql), params).fetchall()]

    def set_class_status(self, class_id: int, status: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                self._sql("UPDATE classes SET status = ?, updated_at = ? WHERE id = ?"),
                (status, dt(utc_now()), class_id),
            )
        return self.get_class(class_id)

    def create_class_session(
        self,
        class_id: int,
        created_by: int,
        name: str,
        ttl_hours: int | None = None,
        session_at: str | None = None,
    ) -> dict[str, Any]:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("課堂名稱不可為空")
        klass = self.get_class(class_id)
        if not klass or klass["status"] != "active":
            raise ValueError("class is not active")
        start = parse_dt(session_at) if session_at else utc_now()
        if start is None:
            start = utc_now()
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        ttl = int(ttl_hours if ttl_hours is not None else klass["api_key_ttl_hours"])
        expires_at = start + timedelta(hours=ttl)
        invite_code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
        now = dt(utc_now())
        with self._connect() as conn:
            session_id = self._insert_returning_id(
                conn,
                """
                INSERT INTO class_sessions(
                    class_id, invite_code, expires_at, session_at, name, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (class_id, invite_code, dt(expires_at), dt(start), cleaned_name, created_by, now),
            )
            row = conn.execute(
                self._sql("SELECT * FROM class_sessions WHERE id = ?"),
                (session_id,),
            ).fetchone()
            return dict(row)

    def list_class_sessions(self, class_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT s.*,
                           (
                               SELECT COUNT(*)
                               FROM session_redemptions r
                               WHERE r.session_id = s.id
                           ) AS redemption_count
                    FROM class_sessions s
                    WHERE s.class_id = ?
                    ORDER BY COALESCE(s.session_at, s.created_at) DESC
                    """
                ),
                (class_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_class_session(
        self,
        class_id: int,
        session_id: int,
        expires_at: str | None = None,
        name: str | None = None,
        image_generation_enabled: bool | None = None,
        tts_enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        if expires_at is None and name is None and image_generation_enabled is None and tts_enabled is None:
            raise ValueError("nothing to update")
        with self._connect() as conn:
            row = conn.execute(
                self._sql("SELECT id FROM class_sessions WHERE id = ? AND class_id = ?"),
                (session_id, class_id),
            ).fetchone()
            if not row:
                return None
            if name is not None:
                cleaned_name = name.strip()
                if not cleaned_name:
                    raise ValueError("課堂名稱不可為空")
                conn.execute(
                    self._sql("UPDATE class_sessions SET name = ? WHERE id = ?"),
                    (cleaned_name, session_id),
                )
            if expires_at is not None:
                conn.execute(
                    self._sql("UPDATE class_sessions SET expires_at = ? WHERE id = ?"),
                    (expires_at, session_id),
                )
                conn.execute(
                    self._sql("UPDATE api_keys SET expires_at = ? WHERE session_id = ?"),
                    (expires_at, session_id),
                )
            if image_generation_enabled is not None:
                conn.execute(
                    self._sql("UPDATE class_sessions SET image_generation_enabled = ? WHERE id = ?"),
                    (1 if image_generation_enabled else 0, session_id),
                )
            if tts_enabled is not None:
                conn.execute(
                    self._sql("UPDATE class_sessions SET tts_enabled = ? WHERE id = ?"),
                    (1 if tts_enabled else 0, session_id),
                )
            updated = conn.execute(
                self._sql("SELECT * FROM class_sessions WHERE id = ?"),
                (session_id,),
            ).fetchone()
            return dict(updated) if updated else None

    def is_image_generation_enabled(self, session_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                self._sql("SELECT image_generation_enabled FROM class_sessions WHERE id = ?"),
                (session_id,),
            ).fetchone()
            if not row:
                return False
            value = row["image_generation_enabled"]
            if isinstance(value, bool):
                return value
            return bool(int(value or 0))

    def is_tts_enabled(self, session_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                self._sql("SELECT tts_enabled FROM class_sessions WHERE id = ?"),
                (session_id,),
            ).fetchone()
            if not row:
                return False
            value = row["tts_enabled"]
            if isinstance(value, bool):
                return value
            return bool(int(value or 0))

    def redeem_invite(self, invite_code: str, user_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            session = conn.execute(
                self._sql(
                    """
                    SELECT s.*, c.name AS class_name, c.status AS class_status
                    FROM class_sessions s JOIN classes c ON c.id = s.class_id
                    WHERE s.invite_code = ?
                    """
                ),
                (invite_code.strip().upper(),),
            ).fetchone()
            if not session or session["status"] != "active" or session["class_status"] != "active":
                raise ValueError("invalid invite")
            if utc_now() >= parse_dt(session["expires_at"]):
                raise ValueError("expired invite")
            now = dt(utc_now())
            self._insert_or_ignore_redemption(conn, int(session["id"]), user_id, now or "")
            self._insert_or_ignore_class_member(conn, int(session["class_id"]), user_id, now or "")
        key = self.issue_session_key(user_id, int(session["id"]))
        return {"api_key": key, "session": dict(session)}

    def list_session_redemptions(self, class_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT s.id AS session_id, s.invite_code, s.expires_at, r.redeemed_at, u.name, u.email
                    FROM class_sessions s
                    LEFT JOIN session_redemptions r ON r.session_id = s.id
                    LEFT JOIN users u ON u.id = r.user_id
                    WHERE s.class_id = ?
                    ORDER BY s.created_at DESC, r.redeemed_at DESC
                    """
                ),
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
        message_preview: str = "",
        messages_json: str = "",
        api_endpoint: str = "",
        response_preview: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                self._sql(
                    """
                    INSERT INTO prompt_logs(
                        user_id, class_id, session_id, raw_prompt, final_prompt, model, status,
                        prompt_tokens, completion_tokens, total_tokens, client_ip, created_at,
                        message_preview, messages_json, api_endpoint, response_preview
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
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
                    dt(utc_now()),
                    message_preview,
                    messages_json,
                    api_endpoint,
                    response_preview,
                ),
            )

    def class_usage(self, teacher_id: int, class_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._sql(
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
                    """
                ),
                (class_id, teacher_id),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                sessions = conn.execute(
                    self._sql(
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
                        """
                    ),
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
            SELECT
                l.id,
                l.user_id,
                l.class_id,
                l.session_id,
                l.raw_prompt,
                l.model,
                l.status,
                l.prompt_tokens,
                l.completion_tokens,
                l.total_tokens,
                l.client_ip,
                l.created_at,
                l.message_preview,
                l.response_preview,
                l.api_endpoint,
                u.name AS user_name,
                u.email AS user_email
            FROM prompt_logs l
            JOIN classes c ON c.id = l.class_id
            LEFT JOIN users u ON u.id = l.user_id
            WHERE c.teacher_id = ? AND l.class_id = ?
        """
        if session_id is not None:
            sql += " AND l.session_id = ?"
            params.append(session_id)
        if keyword:
            sql += " AND (l.raw_prompt LIKE ? OR l.message_preview LIKE ? OR l.response_preview LIKE ? OR u.name LIKE ? OR u.email LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like, like, like])
        if start_at:
            sql += " AND l.created_at >= ?"
            params.append(start_at)
        if end_at:
            sql += " AND l.created_at <= ?"
            params.append(end_at)
        sql += " ORDER BY l.created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(self._sql(sql), params).fetchall()]

    def get_prompt_log(self, teacher_id: int, class_id: int, log_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                self._sql(
                    """
                    SELECT l.messages_json, l.raw_prompt, l.api_endpoint, l.response_preview
                    FROM prompt_logs l
                    JOIN classes c ON c.id = l.class_id
                    WHERE c.teacher_id = ? AND l.class_id = ? AND l.id = ?
                    """
                ),
                (teacher_id, class_id, log_id),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            messages = prompt_log_messages(item.get("messages_json"), item.get("raw_prompt"))
            return {
                "messages": messages,
                "api_endpoint": item.get("api_endpoint") or "",
                "response_preview": item.get("response_preview") or "",
            }

    def get_runtime_settings(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(self._sql("SELECT key, value FROM runtime_settings")).fetchall()
            return {str(row["key"]): str(row["value"]) for row in rows}

    def update_runtime_settings(
        self,
        retention_days: int | None = None,
        student_default_ttl_hours: int | None = None,
        open_registration: bool | None = None,
    ) -> dict[str, str]:
        updates: list[tuple[str, str]] = []
        now = dt(utc_now())
        if retention_days is not None:
            updates.append(("retention_days", str(retention_days)))
        if student_default_ttl_hours is not None:
            updates.append(("student_default_ttl_hours", str(student_default_ttl_hours)))
        if open_registration is not None:
            updates.append(("open_registration", "true" if open_registration else "false"))
        if not updates:
            return self.get_runtime_settings()
        with self._connect() as conn:
            for key, value in updates:
                if self.dialect == "postgres":
                    conn.execute(
                        self._sql(
                            "INSERT INTO runtime_settings(key, value, updated_at) VALUES (?, ?, ?) "
                            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"
                        ),
                        (key, value, now),
                    )
                else:
                    conn.execute(
                        self._sql(
                            "INSERT INTO runtime_settings(key, value, updated_at) VALUES (?, ?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
                        ),
                        (key, value, now),
                    )
        return self.get_runtime_settings()

    def archive_prompt_logs(self, now: datetime | None = None, retention_days: int | None = None) -> dict[str, Any]:
        current = now or utc_now()
        cutoff = current - timedelta(
            days=retention_days if retention_days is not None else self.settings.prompt_logs.retention_days
        )
        with self._connect() as conn:
            rows = conn.execute(
                self._sql(
                    """
                    SELECT l.*
                    FROM prompt_logs l
                    LEFT JOIN classes c ON c.id = l.class_id
                    WHERE c.status = 'ended' OR l.created_at < ?
                    ORDER BY l.created_at
                    """
                ),
                (dt(cutoff),),
            ).fetchall()
            for row in rows:
                self._archive_row(dict(row), current)
            if rows:
                self._executemany(
                    conn,
                    "DELETE FROM prompt_logs WHERE id = ?",
                    [(row["id"],) for row in rows],
                )
        self._after_archive(len(rows))
        return {"archived": len(rows)}

    def _after_archive(self, archived_count: int) -> None:
        return
