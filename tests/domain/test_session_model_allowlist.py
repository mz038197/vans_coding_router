from src.domain.session_model_allowlist import (
    dump_allowlist_json,
    filter_chat_language_models,
    is_model_allowed,
    parse_allowlist_json,
    template_model_ids,
    validate_allowlist,
)
import pytest

TEMPLATE = [
    {
        "name": "VCRouter",
        "vendor": "customendpoint",
        "models": [
            {"id": "ollama_cloud@mini:cloud", "name": "mini"},
            {"id": "openrouter@minimax/minimax-m3", "name": "backup"},
        ],
    }
]


def test_unset_allowlist_keeps_the_whole_template():
    assert filter_chat_language_models(TEMPLATE, None)[0]["models"][0]["id"] == "ollama_cloud@mini:cloud"
    assert len(filter_chat_language_models(TEMPLATE, None)[0]["models"]) == 2


def test_empty_allowlist_keeps_provider_with_no_models():
    filtered = filter_chat_language_models(TEMPLATE, [])
    assert filtered[0]["name"] == "VCRouter"
    assert filtered[0]["models"] == []


def test_subset_allowlist_keeps_only_listed_template_models():
    filtered = filter_chat_language_models(TEMPLATE, ["openrouter@minimax/minimax-m3"])
    ids = [model["id"] for model in filtered[0]["models"]]
    assert ids == ["openrouter@minimax/minimax-m3"]


def test_unset_allows_any_model_id_on_the_api():
    assert is_model_allowed("anything", None) is True
    assert is_model_allowed("ollama_cloud@mini:cloud", []) is False
    assert is_model_allowed("ollama_cloud@mini:cloud", ["ollama_cloud@mini:cloud"]) is True


def test_validate_allowlist_rejects_ids_outside_the_template():
    with pytest.raises(ValueError, match="不在 Router Model Template"):
        validate_allowlist(["unknown@x"], TEMPLATE)
    assert validate_allowlist(["ollama_cloud@mini:cloud", "ollama_cloud@mini:cloud"], TEMPLATE) == [
        "ollama_cloud@mini:cloud"
    ]


def test_parse_and_dump_round_trip_empty_versus_unset():
    assert parse_allowlist_json(None) is None
    assert dump_allowlist_json(None) is None
    assert parse_allowlist_json("[]") == []
    assert dump_allowlist_json([]) == "[]"
    assert template_model_ids(TEMPLATE) == [
        "ollama_cloud@mini:cloud",
        "openrouter@minimax/minimax-m3",
    ]
