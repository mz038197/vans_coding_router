from api_test_utils import build_test_client
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from tests.infrastructure.test_routing_gateway import FakeGateway


def _routing_client(fake_repo, fake_logger):
    ollama = FakeGateway("ollama_cloud")
    openrouter = FakeGateway("openrouter")
    routing = RoutingGateway({"ollama_cloud": ollama, "openrouter": openrouter})
    return build_test_client(fake_repo, routing, fake_logger), ollama, openrouter


def test_models_lists_ollama_with_cloud_suffix(fake_repo, fake_logger):
    client, _, _ = _routing_client(fake_repo, fake_logger)
    response = client.get("/v1/models", headers={"Authorization": "Bearer valid-key"})
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert "ollama_cloud@qwen3-coder-next:cloud" in ids
    assert "openrouter@anthropic/claude-sonnet" in ids


def test_chat_completions_resolves_ollama_model(fake_repo, fake_logger):
    client, ollama, _ = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "ollama_cloud@minimax-m3",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "max_tokens": 16,
        },
    )
    assert response.status_code == 200
    assert ollama.requests == ["minimax-m3:cloud"]


def test_responses_resolves_ollama_model(fake_repo, fake_logger):
    client, ollama, _ = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "ollama_cloud@minimax-m3", "input": "ping", "stream": False},
    )
    assert response.status_code == 200
    assert ollama.requests == ["minimax-m3:cloud"]


def test_responses_keeps_openrouter_colon_tag(fake_repo, fake_logger):
    client, ollama, openrouter = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "openrouter@openai/gpt-oss-120b:free", "input": "ping", "stream": False},
    )
    assert response.status_code == 200
    assert openrouter.requests == ["openai/gpt-oss-120b:free"]
    assert ollama.requests == []
