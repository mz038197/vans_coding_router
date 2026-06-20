import pytest

from src.domain.errors import InvalidModelIdError
from src.infrastructure.routing.model_id import format_model_id, parse_model_id


def test_parse_model_id_openrouter_slug_with_colon_suffix():
    provider, upstream = parse_model_id(
        "openrouter@openai/gpt-oss-120b:free",
        {"openrouter", "ollama_cloud"},
    )
    assert provider == "openrouter"
    assert upstream == "openai/gpt-oss-120b:free"


def test_parse_model_id_ollama_with_tag():
    provider, upstream = parse_model_id(
        "ollama_cloud@gemma3:27b",
        {"openrouter", "ollama_cloud"},
    )
    assert provider == "ollama_cloud"
    assert upstream == "gemma3:27b"


def test_parse_model_id_rejects_bare_name():
    with pytest.raises(InvalidModelIdError):
        parse_model_id("qwen3-coder-next", {"ollama_cloud"})


def test_parse_model_id_rejects_unknown_provider():
    with pytest.raises(InvalidModelIdError, match="未知的 provider"):
        parse_model_id("unknown@foo", {"ollama_cloud"})


def test_parse_model_id_rejects_empty_upstream():
    with pytest.raises(InvalidModelIdError):
        parse_model_id("ollama_cloud@", {"ollama_cloud"})


def test_format_model_id():
    assert format_model_id("openrouter", "anthropic/claude-sonnet-4") == "openrouter@anthropic/claude-sonnet-4"
