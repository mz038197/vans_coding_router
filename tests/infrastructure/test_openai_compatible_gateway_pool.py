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
