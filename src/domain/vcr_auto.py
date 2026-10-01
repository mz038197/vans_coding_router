from __future__ import annotations

import copy
from typing import Any

from src.domain.classroom_model_choice import PICKED_MODELS
from src.domain.model_shelf import is_non_text_shelf_model, omit_non_text_shelf_models

VCR_AUTO_MODEL_ID = "vcr-auto"


def classroom_vscode_model_list(shipped: list[Any]) -> list[dict[str, Any]]:
    """One Copilot model named vcr-auto, fixed to the shipped text model."""
    provider, model = _shipped_text_model(shipped)
    entry = copy.deepcopy(model)
    entry["id"] = VCR_AUTO_MODEL_ID
    entry["name"] = VCR_AUTO_MODEL_ID
    entry["vision"] = True
    entry["toolCalling"] = True
    entry["thinking"] = True
    for key in ("decisionShelf", "imageShelf", "speechShelf", "speechTranscriptionShelf"):
        entry.pop(key, None)
    return [
        {
            "name": provider.get("name"),
            "vendor": provider.get("vendor"),
            "apiKey": provider.get("apiKey", ""),
            "apiType": provider.get("apiType"),
            "models": [entry],
        }
    ]


def classroom_student_chat_document(
    choice: str | None,
    session_document: list[Any] | None,
    shipped: list[Any],
) -> list[Any]:
    if choice == PICKED_MODELS:
        filtered = omit_non_text_shelf_models(session_document)
        return filtered if isinstance(filtered, list) else []
    return classroom_vscode_model_list(shipped)


def _shipped_text_model(shipped: list[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    for provider in shipped:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if (
                isinstance(model, dict)
                and isinstance(model.get("id"), str)
                and model["id"]
                and not is_non_text_shelf_model(model)
            ):
                return provider, model
    raise ValueError("shipped text model is missing")
