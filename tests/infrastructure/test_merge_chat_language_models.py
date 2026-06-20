import copy

from src.infrastructure.vscode.merge_chat_language_models import merge_chat_language_models


def test_merge_into_empty_existing():
    template = [
        {
            "name": "VSRouter",
            "vendor": "customendpoint",
            "apiKey": "",
            "models": [{"id": "ollama_cloud@minimax-m3:cloud", "name": "minimax-m3"}],
        }
    ]
    merged = merge_chat_language_models([], template)
    assert len(merged) == 1
    assert merged[0]["name"] == "VSRouter"
    assert len(merged[0]["models"]) == 1


def test_merge_appends_provider_without_overwriting_existing():
    existing = [
        {
            "name": "Other",
            "vendor": "customoai",
            "apiKey": "keep-me",
            "models": [{"id": "other-model", "name": "Other Model"}],
        }
    ]
    template = [
        {
            "name": "VSRouter",
            "vendor": "customendpoint",
            "apiKey": "",
            "models": [{"id": "ollama_cloud@minimax-m3:cloud", "name": "minimax-m3"}],
        }
    ]
    merged = merge_chat_language_models(existing, template)
    assert len(merged) == 2
    assert merged[0]["apiKey"] == "keep-me"
    assert merged[1]["name"] == "VSRouter"


def test_merge_appends_models_and_preserves_api_key():
    existing = [
        {
            "name": "VSRouter",
            "vendor": "customendpoint",
            "apiKey": "student-secret",
            "models": [{"id": "ollama_cloud@minimax-m3:cloud", "name": "minimax-m3", "url": "https://old"}],
        }
    ]
    template = [
        {
            "name": "VSRouter",
            "vendor": "customendpoint",
            "apiKey": "",
            "models": [
                {"id": "ollama_cloud@minimax-m3:cloud", "name": "minimax-m3", "url": "https://new"},
                {"id": "ollama_cloud@qwen3.5:cloud", "name": "qwen3.5:cloud", "url": "https://ai.vanscoding.com/v1"},
            ],
        }
    ]
    merged = merge_chat_language_models(existing, template)
    assert merged[0]["apiKey"] == "student-secret"
    assert len(merged[0]["models"]) == 2
    assert merged[0]["models"][0]["url"] == "https://old"
    assert merged[0]["models"][1]["id"] == "ollama_cloud@qwen3.5:cloud"


def test_merge_does_not_mutate_inputs():
    existing = [{"name": "VSRouter", "vendor": "customendpoint", "models": []}]
    template = [{"name": "VSRouter", "vendor": "customendpoint", "models": [{"id": "a", "name": "A"}]}]
    existing_copy = copy.deepcopy(existing)
    template_copy = copy.deepcopy(template)
    merge_chat_language_models(existing, template)
    assert existing == existing_copy
    assert template == template_copy
