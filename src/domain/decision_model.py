from __future__ import annotations

import copy
from typing import Any

DECISION_MODEL_UNCHANGED = object()
OPENROUTER_MODEL_PREFIX = "openrouter@"
DECISION_SHELF_KEY = "decisionShelf"


def normalize_decision_model(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("決策模型必須是 Model ID 或空字串")
    return value.strip()


def is_decision_shelf_model(model: Any) -> bool:
    return (
        isinstance(model, dict)
        and model.get(DECISION_SHELF_KEY) is True
        and isinstance(model.get("id"), str)
        and model["id"].startswith(OPENROUTER_MODEL_PREFIX)
    )


def decision_model_ids(document: list[Any] | None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for provider in document or []:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not is_decision_shelf_model(model):
                continue
            model_id = model["id"]
            if model_id in seen:
                continue
            seen.add(model_id)
            ids.append(model_id)
    return ids


def omit_decision_models_from_document(document: list[Any] | None) -> list[Any] | None:
    if document is None:
        return None
    result = copy.deepcopy(document)
    for provider in result:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        provider["models"] = [
            model for model in models if not is_decision_shelf_model(model)
        ]
    return result


