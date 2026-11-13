from dataclasses import dataclass, field, replace
import os
import re
from pathlib import Path
from ipaddress import ip_address
from urllib.parse import urlparse
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
    dev_auth_enabled: bool = False


@dataclass(frozen=True)
class DatabaseSettings:
    path: str = "~/.vans_coding_router/router.db"
    archive_dir: str = "~/.vans_coding_router/archive"
    url: str = ""


@dataclass(frozen=True)
class PromptLogSettings:
    archive_after_days: int = 15
    delete_after_days: int = 30


@dataclass(frozen=True)
class WebSearchSettings:
    """One search key, held as a secret. The config names the env var, never the key."""

    api_key_env: str = ""


def resolve_web_search_api_key(web_search: WebSearchSettings) -> str:
    if not web_search.api_key_env:
        return ""
    return os.getenv(web_search.api_key_env) or ""


KEY_CHECK_CALLS_PER_MINUTE_PER_SERVICE = 600


@dataclass(frozen=True)
class KeyCheckSettings:
    """Each Partner Service may call Key Check this many times a minute (ADR 0076)."""

    calls_per_minute_per_service: int = KEY_CHECK_CALLS_PER_MINUTE_PER_SERVICE


def _parse_key_check_settings(raw: dict[str, Any] | None) -> KeyCheckSettings:
    data = raw or {}
    if "calls_per_minute_per_service" not in data:
        return KeyCheckSettings()
    value = data["calls_per_minute_per_service"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("key_check.calls_per_minute_per_service must be a positive whole number")
    return KeyCheckSettings(calls_per_minute_per_service=value)


OAUTH_SCOPE_TOKEN = re.compile(r"[\x21\x23-\x5b\x5d-\x7e]+")


@dataclass(frozen=True)
class OAuthClientSettings:
    """One OAuth Client of the Authorization Page (ADR 0094).

    A client with a secret names either the secret's SHA-256 hex (`client_secret_sha256`)
    or the env var that holds it (`client_secret_env`), never the secret itself. A client
    with neither is a public client and proves itself by PKCE alone.
    """

    client_id: str
    redirect_uris: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    name: str = ""
    client_secret_sha256: str = ""
    client_secret_env: str = ""

    @property
    def has_secret(self) -> bool:
        return bool(self.client_secret_sha256 or self.client_secret_env)


@dataclass(frozen=True)
class OAuthSettings:
    clients: dict[str, OAuthClientSettings] = field(default_factory=dict)


def _parse_oauth_settings(raw: dict[str, Any] | None) -> OAuthSettings:
    data = raw or {}
    raw_clients = data.get("clients") or {}
    if not isinstance(raw_clients, dict):
        raise ValueError("oauth.clients must map each client id to its settings")
    clients: dict[str, OAuthClientSettings] = {}
    for raw_id, item in raw_clients.items():
        client_id = str(raw_id).strip()
        if not client_id or not isinstance(item, dict):
            raise ValueError("oauth.clients entries need a client id and a mapping")
        redirect_uris = item.get("redirect_uris") or []
        if not isinstance(redirect_uris, list) or not redirect_uris:
            raise ValueError(f"oauth.clients.{client_id}.redirect_uris must be a non-empty list")
        raw_scopes = item.get("scopes") or []
        if isinstance(raw_scopes, str):
            raw_scopes = [raw_scopes]
        scopes = tuple(token for value in raw_scopes for token in str(value).split())
        if not scopes or any(OAUTH_SCOPE_TOKEN.fullmatch(token) is None for token in scopes):
            raise ValueError(f"oauth.clients.{client_id}.scopes must list scope tokens")
        secret_sha256 = str(item.get("client_secret_sha256") or "").strip().lower()
        if secret_sha256 and re.fullmatch(r"[0-9a-f]{64}", secret_sha256) is None:
            raise ValueError(f"oauth.clients.{client_id}.client_secret_sha256 must be 64 hex")
        secret_env = str(item.get("client_secret_env") or "").strip()
        if secret_sha256 and secret_env:
            raise ValueError(
                f"oauth.clients.{client_id}: set client_secret_sha256 or client_secret_env, not both"
            )
        clients[client_id] = OAuthClientSettings(
            client_id=client_id,
            redirect_uris=tuple(str(uri).strip() for uri in redirect_uris),
            scopes=scopes,
            name=str(item.get("name") or ""),
            client_secret_sha256=secret_sha256,
            client_secret_env=secret_env,
        )
    return OAuthSettings(clients=clients)


CAPABILITY_AUDIO_SPEECH = "audio_speech"
CAPABILITY_AUDIO_TRANSCRIPTION = "audio_transcription"


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    type: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    api_key_envs: tuple[str, ...] = ()
    max_concurrent_per_key: int = 0
    queue_timeout_sec: float = 120.0
    acquire_delay_ms: int = 0
    quarantine_ttl_sec: float = 3600.0
    enabled: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()


def resolve_provider_api_keys(provider: ProviderSettings) -> list[str]:
    """Resolve upstream API keys from api_key_envs, else api_key / api_key_env."""
    if provider.api_key_envs:
        keys = [
            value
            for env_name in provider.api_key_envs
            if (value := (os.getenv(env_name) or ""))
        ]
        if keys:
            return keys
    if provider.api_key:
        return [provider.api_key]
    if provider.api_key_env:
        value = os.getenv(provider.api_key_env) or ""
        if value:
            return [value]
    return []


_SPEECH_ONLY_CAPABILITIES = frozenset(
    {CAPABILITY_AUDIO_SPEECH, CAPABILITY_AUDIO_TRANSCRIPTION}
)


def provider_supports(provider: ProviderSettings, capability: str) -> bool:
    return capability in provider.capabilities


def is_speech_only_provider(provider: ProviderSettings) -> bool:
    caps = frozenset(provider.capabilities)
    return bool(caps) and caps <= _SPEECH_ONLY_CAPABILITIES


def provider_has_kind_split(name: str) -> bool:
    """OpenRouter's model list can be filtered by output kind. Other lists cannot."""
    return name == "openrouter"


def classroom_chat_provider_names(providers: dict[str, ProviderSettings]) -> list[str]:
    return [
        name
        for name, provider in providers.items()
        if provider.enabled and not is_speech_only_provider(provider)
    ]


def providers_with_capability(
    providers: dict[str, ProviderSettings],
    capability: str,
    *,
    enabled_only: bool = True,
) -> list[str]:
    names: list[str] = []
    for name, provider in providers.items():
        if enabled_only and not provider.enabled:
            continue
        if provider_supports(provider, capability):
            names.append(name)
    return names


@dataclass(frozen=True)
class RoutingSettings:
    default_provider: str = ""


@dataclass(frozen=True)
class RouterSettings:
    path: str | None = None
    public_url: str = "http://127.0.0.1:8000"
    auth: AuthSettings = field(default_factory=AuthSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    prompt_logs: PromptLogSettings = field(default_factory=PromptLogSettings)
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    routing: RoutingSettings = field(default_factory=RoutingSettings)
    web_search: WebSearchSettings = field(default_factory=WebSearchSettings)
    key_check: KeyCheckSettings = field(default_factory=KeyCheckSettings)
    oauth: OAuthSettings = field(default_factory=OAuthSettings)


def is_loopback_url(url: str) -> bool:
    host = urlparse(url).hostname
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def validate_portal_auth_settings(settings: RouterSettings) -> None:
    if is_loopback_url(settings.public_url):
        return
    if settings.auth.dev_auth_enabled:
        raise ValueError("Development login is only allowed on a loopback public URL")
    if not (settings.auth.google_client_id and settings.auth.google_client_secret):
        raise ValueError("Google OAuth configuration is required for public deployment")


def _parse_prompt_log_settings(raw: dict[str, Any] | None) -> PromptLogSettings:
    data = raw or {}
    if "archive_after_days" in data:
        archive_after_days = int(data["archive_after_days"])
    elif "retention_days" in data:
        archive_after_days = int(data["retention_days"])
    else:
        archive_after_days = 15
    delete_after_days = int(data["delete_after_days"]) if "delete_after_days" in data else 30
    return PromptLogSettings(archive_after_days=archive_after_days, delete_after_days=delete_after_days)


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
    web_search = data.get("web_search") or {}

    return _apply_env_overrides(RouterSettings(
        path=str(config_path),
        public_url=str(data.get("public_url", "http://127.0.0.1:8000")),
        auth=AuthSettings(
            teacher_domain=str(auth.get("teacher_domain", "")).lower(),
            admin_emails=tuple(str(e).lower() for e in auth.get("admin_emails", [])),
            session_secret=str(auth.get("session_secret", "dev-session-secret")),
            google_client_id=str(auth.get("google_client_id", "")),
            google_client_secret=str(auth.get("google_client_secret", "")),
            open_registration=bool(auth.get("open_registration", True)),
            dev_auth_enabled=bool(auth.get("dev_auth_enabled", False)),
        ),
        database=DatabaseSettings(
            path=str(database.get("path", "~/.vans_coding_router/router.db")),
            archive_dir=str(database.get("archive_dir", "~/.vans_coding_router/archive")),
            url=str(database.get("url", "")),
        ),
        prompt_logs=_parse_prompt_log_settings(prompt_logs),
        providers=providers,
        routing=RoutingSettings(
            default_provider=str(routing.get("default_provider", "")),
        ),
        web_search=WebSearchSettings(
            api_key_env=str(web_search.get("api_key_env", "")),
        ),
        key_check=_parse_key_check_settings(data.get("key_check")),
        oauth=_parse_oauth_settings(data.get("oauth")),
    ))


def _load_providers(raw: dict[str, Any]) -> dict[str, ProviderSettings]:
    providers: dict[str, ProviderSettings] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            continue
        raw_capabilities = item.get("capabilities") or ()
        capabilities = tuple(str(c) for c in raw_capabilities) if isinstance(raw_capabilities, list) else ()
        raw_key_envs = item.get("api_key_envs") or ()
        api_key_envs = tuple(str(e) for e in raw_key_envs) if isinstance(raw_key_envs, list) else ()
        providers[str(name)] = ProviderSettings(
            name=str(name),
            type=str(item.get("type", "openai_compatible")),
            base_url=str(item.get("base_url", "")).rstrip("/"),
            api_key=str(item.get("api_key", "")),
            api_key_env=str(item.get("api_key_env", "")),
            api_key_envs=api_key_envs,
            max_concurrent_per_key=int(item.get("max_concurrent_per_key", 0)),
            queue_timeout_sec=float(item.get("queue_timeout_sec", 120)),
            acquire_delay_ms=int(item.get("acquire_delay_ms", 0)),
            quarantine_ttl_sec=float(item.get("quarantine_ttl_sec", 3600)),
            enabled=bool(item.get("enabled", True)),
            extra_headers={str(k): str(v) for k, v in (item.get("extra_headers") or {}).items()},
            capabilities=capabilities,
        )
    return providers


def _env(name: str, current: str = "") -> str:
    return os.getenv(name) or current


def _env_bool(name: str, current: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return current
    return value.strip().lower() in {"true", "1", "yes"}


def _apply_env_overrides(settings: RouterSettings) -> RouterSettings:
    auth = AuthSettings(
        teacher_domain=settings.auth.teacher_domain,
        admin_emails=settings.auth.admin_emails,
        session_secret=_env("SESSION_SECRET", settings.auth.session_secret),
        google_client_id=_env("GOOGLE_CLIENT_ID", settings.auth.google_client_id),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET", settings.auth.google_client_secret),
        open_registration=settings.auth.open_registration,
        dev_auth_enabled=_env_bool("DEV_AUTH_ENABLED", settings.auth.dev_auth_enabled),
    )
    database = DatabaseSettings(
        path=settings.database.path,
        archive_dir=settings.database.archive_dir,
        url=_env("DATABASE_URL", settings.database.url),
    )
    return RouterSettings(
        path=settings.path,
        public_url=_env("PUBLIC_URL", settings.public_url),
        auth=auth,
        database=database,
        prompt_logs=settings.prompt_logs,
        providers=settings.providers,
        routing=settings.routing,
        web_search=settings.web_search,
        key_check=settings.key_check,
        oauth=settings.oauth,
    )


def apply_runtime_settings(base: RouterSettings, overrides: dict[str, str]) -> RouterSettings:
    if not overrides:
        return base
    archive_after_days = base.prompt_logs.archive_after_days
    delete_after_days = base.prompt_logs.delete_after_days
    open_registration = base.auth.open_registration
    if "archive_after_days" in overrides:
        archive_after_days = int(overrides["archive_after_days"])
    elif "retention_days" in overrides:
        archive_after_days = int(overrides["retention_days"])
    if "delete_after_days" in overrides:
        delete_after_days = int(overrides["delete_after_days"])
    if "open_registration" in overrides:
        open_registration = overrides["open_registration"].lower() in ("true", "1", "yes")
    return RouterSettings(
        path=base.path,
        public_url=base.public_url,
        auth=replace(base.auth, open_registration=open_registration),
        database=base.database,
        prompt_logs=replace(
            base.prompt_logs,
            archive_after_days=archive_after_days,
            delete_after_days=delete_after_days,
        ),
        providers=base.providers,
        routing=base.routing,
        web_search=base.web_search,
        key_check=base.key_check,
        oauth=base.oauth,
    )


def settings_summary(settings: RouterSettings) -> dict[str, Any]:
    config_path = settings.path or ""
    return {
        "config_path": settings.path,
        "config_writable": not config_path.startswith("/etc/secrets/"),
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
        "prompt_logs": {
            "archive_after_days": settings.prompt_logs.archive_after_days,
            "delete_after_days": settings.prompt_logs.delete_after_days,
        },
        "providers": {
            name: {
                "type": provider.type,
                "base_url": provider.base_url,
                "api_key": "***"
                if provider.api_key or provider.api_key_env or provider.api_key_envs
                else "",
                "api_keys": len(provider.api_key_envs)
                if provider.api_key_envs
                else (1 if (provider.api_key or provider.api_key_env) else 0),
                "max_concurrent_per_key": provider.max_concurrent_per_key,
                "queue_timeout_sec": provider.queue_timeout_sec,
                "acquire_delay_ms": provider.acquire_delay_ms,
                "enabled": provider.enabled,
                "capabilities": list(provider.capabilities),
            }
            for name, provider in settings.providers.items()
        },
        "routing": {
            "default_provider": settings.routing.default_provider,
        },
    }


def update_non_secret_settings(
    path: str,
    archive_after_days: int | None = None,
    delete_after_days: int | None = None,
    open_registration: bool | None = None,
) -> RouterSettings:
    config_path = Path(path).expanduser()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    data = data or {}
    if archive_after_days is not None or delete_after_days is not None:
        prompt_logs = data.setdefault("prompt_logs", {})
        if archive_after_days is not None:
            prompt_logs["archive_after_days"] = archive_after_days
            prompt_logs.pop("retention_days", None)
        if delete_after_days is not None:
            prompt_logs["delete_after_days"] = delete_after_days
    if open_registration is not None:
        data.setdefault("auth", {})["open_registration"] = open_registration
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return load_router_settings(str(config_path))
