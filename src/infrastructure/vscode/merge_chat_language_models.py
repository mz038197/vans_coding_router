from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

VANS_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "config" / "chatLanguageModels.vans.json"


def provider_key(provider: dict[str, Any]) -> tuple[Any, Any]:
    return provider.get("vendor"), provider.get("name")


def merge_chat_language_models(
    existing: list[dict[str, Any]] | None,
    template: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = copy.deepcopy(existing or [])
    index = {provider_key(provider): provider for provider in merged if isinstance(provider, dict)}

    for template_provider in template:
        if not isinstance(template_provider, dict):
            continue
        key = provider_key(template_provider)
        if key not in index:
            merged.append(copy.deepcopy(template_provider))
            index[key] = merged[-1]
            continue

        target = index[key]
        existing_models = target.get("models")
        if not isinstance(existing_models, list):
            existing_models = []
            target["models"] = existing_models

        model_ids = {
            model.get("id")
            for model in existing_models
            if isinstance(model, dict) and model.get("id")
        }
        template_models = template_provider.get("models")
        if not isinstance(template_models, list):
            continue
        for template_model in template_models:
            if not isinstance(template_model, dict):
                continue
            model_id = template_model.get("id")
            if model_id and model_id in model_ids:
                continue
            existing_models.append(copy.deepcopy(template_model))
            if model_id:
                model_ids.add(model_id)

    return merged


def load_vans_template() -> list[dict[str, Any]]:
    data = json.loads(VANS_TEMPLATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("chatLanguageModels.vans.json must be a JSON array")
    return data
