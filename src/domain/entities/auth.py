from dataclasses import dataclass


@dataclass(frozen=True)
class AuthContext:
    user_id: int | None
    email: str | None
    name: str | None
    role: str | None = None
    roles: tuple[str, ...] = ()
    is_admin: bool = False
    api_key_id: int | None = None
    session_id: int | None = None
    class_id: int | None = None
    key_prefix: str | None = None

    @property
    def teacher_name(self) -> str | None:
        return self.name or self.email
