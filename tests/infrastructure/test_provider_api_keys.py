from pathlib import Path

from src.infrastructure.config import (
    ProviderSettings,
    load_router_settings,
    resolve_provider_api_keys,
)


def test_resolve_api_key_envs_collects_non_empty(monkeypatch):
    monkeypatch.setenv("K1", "alpha")
    monkeypatch.setenv("K2", "beta")
    monkeypatch.delenv("K3", raising=False)
    provider = ProviderSettings(
        name="ollama_cloud",
        api_key_envs=("K1", "K2", "K3"),
        api_key_env="IGNORED",
    )
    assert resolve_provider_api_keys(provider) == ["alpha", "beta"]


def test_resolve_falls_back_to_single_api_key_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "only-one")
    provider = ProviderSettings(name="ollama_cloud", api_key_env="OLLAMA_CLOUD_API_KEY")
    assert resolve_provider_api_keys(provider) == ["only-one"]


def test_resolve_falls_back_when_api_key_envs_all_empty(monkeypatch):
    monkeypatch.delenv("K1", raising=False)
    monkeypatch.delenv("K2", raising=False)
    monkeypatch.setenv("FALLBACK_KEY", "fallback")
    provider = ProviderSettings(
        name="ollama_cloud",
        api_key_envs=("K1", "K2"),
        api_key_env="FALLBACK_KEY",
    )
    assert resolve_provider_api_keys(provider) == ["fallback"]


def test_resolve_falls_back_to_inline_api_key_when_envs_empty(monkeypatch):
    monkeypatch.delenv("K1", raising=False)
    provider = ProviderSettings(
        name="ollama_cloud",
        api_key_envs=("K1",),
        api_key="inline-key",
    )
    assert resolve_provider_api_keys(provider) == ["inline-key"]


def test_load_providers_reads_queue_settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "a")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_2", "b")
    config = tmp_path / "router.yaml"
    config.write_text(
        """
providers:
  ollama_cloud:
    type: openai_compatible
    base_url: "https://ollama.com/v1"
    api_key_envs:
      - OLLAMA_CLOUD_API_KEY
      - OLLAMA_CLOUD_API_KEY_2
    max_concurrent_per_key: 3
    queue_timeout_sec: 90
    acquire_delay_ms: 200
    enabled: true
""",
        encoding="utf-8",
    )
    settings = load_router_settings(str(config))
    provider = settings.providers["ollama_cloud"]
    assert provider.api_key_envs == ("OLLAMA_CLOUD_API_KEY", "OLLAMA_CLOUD_API_KEY_2")
    assert provider.max_concurrent_per_key == 3
    assert provider.queue_timeout_sec == 90
    assert provider.acquire_delay_ms == 200
    assert resolve_provider_api_keys(provider) == ["a", "b"]


def test_shipped_openrouter_configs_limit_concurrency(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "or-key-2")
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "config/router.example.yaml",
        "config/router.stg.example.yaml",
        "config/router.prod.yaml",
    ):
        settings = load_router_settings(str(root / relative))
        provider = settings.providers["openrouter"]
        assert provider.api_key_envs == ("OPENROUTER_API_KEY", "OPENROUTER_API_KEY_2")
        assert provider.max_concurrent_per_key == 6
        assert provider.queue_timeout_sec == 120
        assert provider.acquire_delay_ms == 200
        assert provider.quarantine_ttl_sec == 3600
        assert resolve_provider_api_keys(provider) == ["or-key", "or-key-2"]


def test_shipped_openrouter_second_key_optional(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("OPENROUTER_API_KEY_2", raising=False)
    root = Path(__file__).resolve().parents[2]
    settings = load_router_settings(str(root / "config/router.prod.yaml"))
    assert resolve_provider_api_keys(settings.providers["openrouter"]) == ["or-key"]
