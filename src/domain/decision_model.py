from __future__ import annotations

import copy
from typing import Any

DECISION_MODEL_UNCHANGED = object()
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
        and bool(model["id"])
    )


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


