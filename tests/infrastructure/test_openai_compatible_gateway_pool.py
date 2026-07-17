from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway


def test_gateway_shares_single_pool_instance(monkeypatch):
    monkeypatch.setenv("K1", "a")
    monkeypatch.setenv("K2", "b")
    gateway = OpenAICompatibleGateway(
        ProviderSettings(
            name="ollama_cloud",
            type="openai_compatible",
            base_url="https://ollama.com/v1",
            api_key_envs=("K1", "K2"),
            max_concurrent_per_key=3,
        ),
        timeout=30.0,
    )
    assert gateway._pool is not None
    assert gateway._ensure_pool() is gateway._pool
    assert gateway._ensure_pool() is gateway._pool
    assert gateway._pool.key_count == 2


def test_gateway_pool_status_labels_and_hides_secrets(monkeypatch):
    monkeypatch.setenv("K1", "secret-a")
    monkeypatch.setenv("K2", "secret-b")
    gateway = OpenAICompatibleGateway(
        ProviderSettings(
            name="ollama_cloud",
            type="openai_compatible",
            base_url="https://ollama.com/v1",
            api_key_envs=("K1", "K2"),
            max_concurrent_per_key=3,
        ),
        timeout=30.0,
    )
    status = gateway.pool_status(limited_only=True)
    assert status is not None
    assert status["capacity"] == 6
    assert [item["label"] for item in status["keys"]] == ["OLLAMA_CLOUD 1", "OLLAMA_CLOUD 2"]
    assert "secret-a" not in str(status)
    assert "secret-b" not in str(status)


def test_gateway_pool_status_limited_only_skips_unlimited(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret")
    gateway = OpenAICompatibleGateway(
        ProviderSettings(
            name="openrouter",
            type="openai_compatible",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            max_concurrent_per_key=0,
        ),
        timeout=30.0,
    )
    assert gateway.pool_status(limited_only=True) is None
    unlimited = gateway.pool_status(limited_only=False)
    assert unlimited is not None
    assert unlimited["capacity"] is None
    assert unlimited["keys"][0]["label"] == "OPENROUTER 1"
