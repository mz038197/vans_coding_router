from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AuthSettings:
    teacher_domain: str = ""
    admin_emails: tuple[str, ...] = ()
    session_secret: str = "dev-session-secret"
    google_client_id: str = ""
    google_client_secret: str = ""
    open_registration: bool = True


@dataclass(frozen=True)
class DatabaseSettings:
    path: str = "~/.vans_coding_router/router.db"
    archive_dir: str = "~/.vans_coding_router/archive"
    url: str = ""


@dataclass(frozen=True)
class PromptLogSettings:
    retention_days: int = 30


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    type: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    enabled: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingRuleSettings:
    match: str
    provider: str


@dataclass(frozen=True)
class RoutingSettings:
    default_provider: str = ""
    rules: tuple[RoutingRuleSettings, ...] = ()


@dataclass(frozen=True)
class RouterSettings:
    path: str | None = None
    public_url: str = "http://127.0.0.1:8000"
    student_default_ttl_hours: int = 2
    auth: AuthSettings = field(default_factory=AuthSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    prompt_logs: PromptLogSettings = field(default_factory=PromptLogSettings)
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    routing: RoutingSettings = field(default_factory=RoutingSettings)


def load_router_settings(path: str | None = None) -> RouterSettings:
    config_path = Path(path).expanduser() if path else Path("~/.vans_coding_router/router.yaml").expanduser()
    if not config_path.exists():
        return _apply_env_overrides(RouterSettings(path=str(config_path)))

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    auth = data.get("auth") or {}
    database = data.get("database") or {}
    prompt_logs = data.get("prompt_logs") or {}
    providers = _load_providers(data.get("providers") or {})
    routing = data.get("routing") or {}

    return _apply_env_overrides(RouterSettings(
        path=str(config_path),
        public_url=str(data.get("public_url", "http://127.0.0.1:8000")),
        student_default_ttl_hours=int(data.get("student_default_ttl_hours", 2)),
        auth=AuthSettings(
            teacher_domain=str(auth.get("teacher_domain", "")).lower(),
            admin_emails=tuple(str(e).lower() for e in auth.get("admin_emails", [])),
            session_secret=str(auth.get("session_secret", "dev-session-secret")),
            google_client_id=str(auth.get("google_client_id", "")),
            google_client_secret=str(auth.get("google_client_secret", "")),
            open_registration=bool(auth.get("open_registration", True)),
        ),
        database=DatabaseSettings(
            path=str(database.get("path", "~/.vans_coding_router/router.db")),
            archive_dir=str(database.get("archive_dir", "~/.vans_coding_router/archive")),
            url=str(database.get("url", "")),
        ),
        prompt_logs=PromptLogSettings(retention_days=int(prompt_logs.get("retention_days", 30))),
        providers=providers,
        routing=RoutingSettings(
            default_provider=str(routing.get("default_provider", "")),
            rules=tuple(
                RoutingRuleSettings(match=str(rule.get("match", "")), provider=str(rule.get("provider", "")))
                for rule in routing.get("rules", [])
                if isinstance(rule, dict)
            ),
        ),
    ))


def _load_providers(raw: dict[str, Any]) -> dict[str, ProviderSettings]:
    providers: dict[str, ProviderSettings] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            continue
        providers[str(name)] = ProviderSettings(
            name=str(name),
            type=str(item.get("type", "openai_compatible")),
            base_url=str(item.get("base_url", "")).rstrip("/"),
            api_key=str(item.get("api_key", "")),
            api_key_env=str(item.get("api_key_env", "")),
            enabled=bool(item.get("enabled", True)),
            extra_headers={str(k): str(v) for k, v in (item.get("extra_headers") or {}).items()},
        )
    return providers


def _env(name: str, current: str = "") -> str:
    return os.getenv(name) or current


def _apply_env_overrides(settings: RouterSettings) -> RouterSettings:
    auth = AuthSettings(
        teacher_domain=settings.auth.teacher_domain,
        admin_emails=settings.auth.admin_emails,
        session_secret=_env("SESSION_SECRET", settings.auth.session_secret),
        google_client_id=_env("GOOGLE_CLIENT_ID", settings.auth.google_client_id),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET", settings.auth.google_client_secret),
        open_registration=settings.auth.open_registration,
    )
    database = DatabaseSettings(
        path=settings.database.path,
        archive_dir=settings.database.archive_dir,
        url=_env("DATABASE_URL", settings.database.url),
    )
    return RouterSettings(
        path=settings.path,
        public_url=_env("PUBLIC_URL", settings.public_url),
        student_default_ttl_hours=settings.student_default_ttl_hours,
        auth=auth,
        database=database,
        prompt_logs=settings.prompt_logs,
        providers=settings.providers,
        routing=settings.routing,
    )


def settings_summary(settings: RouterSettings) -> dict[str, Any]:
    return {
        "config_path": settings.path,
        "public_url": settings.public_url,
        "database_path": settings.database.path,
        "database_url": "***" if settings.database.url else "",
        "archive_dir": settings.database.archive_dir,
        "auth": {
            "teacher_domain": settings.auth.teacher_domain,
            "admin_emails": list(settings.auth.admin_emails),
            "google_client_id": settings.auth.google_client_id,
            "google_client_secret": "***" if settings.auth.google_client_secret else "",
            "open_registration": settings.auth.open_registration,
        },
        "student_default_ttl_hours": settings.student_default_ttl_hours,
        "prompt_logs": {"retention_days": settings.prompt_logs.retention_days},
        "providers": {
            name: {
                "type": provider.type,
                "base_url": provider.base_url,
                "api_key": "***" if provider.api_key or provider.api_key_env else "",
                "enabled": provider.enabled,
            }
            for name, provider in settings.providers.items()
        },
        "routing": {
            "default_provider": settings.routing.default_provider,
            "rules": [{"match": rule.match, "provider": rule.provider} for rule in settings.routing.rules],
        },
    }


def update_non_secret_settings(
    path: str,
    retention_days: int | None = None,
    student_default_ttl_hours: int | None = None,
    open_registration: bool | None = None,
) -> RouterSettings:
    config_path = Path(path).expanduser()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    data = data or {}
    if student_default_ttl_hours is not None:
        data["student_default_ttl_hours"] = student_default_ttl_hours
    if retention_days is not None:
        data.setdefault("prompt_logs", {})["retention_days"] = retention_days
    if open_registration is not None:
        data.setdefault("auth", {})["open_registration"] = open_registration
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return load_router_settings(str(config_path))
