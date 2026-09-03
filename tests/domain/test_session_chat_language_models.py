import pytest

from src.domain.session_model_allowlist import (
    VCROUTER_STENCIL,
    default_vcrouter_model,
    normalize_session_chat_language_models,
)

STENCIL_URL = "https://ai.vanscoding.com/v1"
STENCIL_HEADERS = {"Authorization": "Bearer ${apiKey}"}


def test_empty_document_normalizes_to_one_vcrouter_provider_with_no_models():
    assert normalize_session_chat_language_models([]) == [
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "apiKey": "",
            "apiType": "responses",
            "models": [],
        }
    ]


def test_save_forces_routing_fields_to_vcrouter_stencil_and_keeps_other_fields():
    uploaded = [
        {
            "name": "EvilRouter",
            "vendor": "openai",
            "apiType": "chat",
            "apiKey": "sk-leak",
            "models": [
                {
                    "id": "openrouter@minimax/minimax-m3",
                    "name": "sitting-label",
                    "url": "https://evil.example/v1",
                    "requestHeaders": {"Authorization": "Bearer leaked"},
                    "thinking": False,
                    "maxInputTokens": 111,
                    "maxOutputTokens": 22,
                    "toolCalling": False,
                }
            ],
        }
    ]

    normalized = normalize_session_chat_language_models(uploaded)

    assert len(normalized) == 1
    provider = normalized[0]
    assert provider["name"] == "VCRouter"
    assert provider["vendor"] == "customendpoint"
    assert provider["apiType"] == "responses"
    assert provider["apiKey"] == ""
    model = provider["models"][0]
    assert model["id"] == "openrouter@minimax/minimax-m3"
    assert model["name"] == "sitting-label"
    assert model["url"] == STENCIL_URL
    assert model["requestHeaders"] == STENCIL_HEADERS
    assert model["thinking"] is False
    assert model["maxInputTokens"] == 111
    assert model["maxOutputTokens"] == 22
    assert model["toolCalling"] is False


def test_upload_keeps_only_one_vcrouter_provider_when_file_has_two():
    uploaded = [
        {
            "name": "OpenAI",
            "vendor": "openai",
            "models": [{"id": "openai@gpt-4o", "name": "gpt"}],
        },
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "models": [{"id": "ollama_cloud@mini:cloud", "name": "mini"}],
        },
    ]

    normalized = normalize_session_chat_language_models(uploaded)
    assert len(normalized) == 1
    ids = [model["id"] for model in normalized[0]["models"]]
    assert ids == ["openai@gpt-4o", "ollama_cloud@mini:cloud"]
    assert normalized[0]["name"] == "VCRouter"
    assert normalized[0]["vendor"] == "customendpoint"


def test_missing_model_id_rejects_the_whole_document():
    with pytest.raises(ValueError, match="id"):
        normalize_session_chat_language_models(
            [{"name": "VCRouter", "vendor": "customendpoint", "models": [{"name": "no-id"}]}]
        )


def test_non_array_document_is_rejected():
    with pytest.raises(ValueError):
        normalize_session_chat_language_models({"name": "VCRouter"})


def test_checking_a_catalog_row_uses_vcrouter_defaults():
    model = default_vcrouter_model("ollama_cloud@kimi-k2.7-code:cloud", "kimi-k2.7-code")
    assert model["id"] == "ollama_cloud@kimi-k2.7-code:cloud"
    assert model["name"] == "kimi-k2.7-code"
    assert model["url"] == STENCIL_URL
    assert model["requestHeaders"] == STENCIL_HEADERS
    assert model["thinking"] is True
    assert model["maxInputTokens"] == VCROUTER_STENCIL["maxInputTokens"]
    assert model["maxOutputTokens"] == VCROUTER_STENCIL["maxOutputTokens"]
