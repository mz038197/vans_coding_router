from __future__ import annotations

import copy
from typing import Any

from src.domain.session_model_allowlist import template_model_ids

DECISION_MODEL_UNCHANGED = object()
OPENROUTER_MODEL_PREFIX = "openrouter@"
DECISION_MODEL_CLEARED_WARNING = "所選決策模型已不在本課 OpenRouter 清單，已改為空（決策關閉）。"


def normalize_decision_model(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("決策模型必須是 Model ID 或空字串")
    return value.strip()


def openrouter_model_ids(document: list[Any] | None) -> list[str]:
    return [
        model_id
        for model_id in template_model_ids(document or [])
        if model_id.startswith(OPENROUTER_MODEL_PREFIX)
    ]


def effective_decision_model(stored: str | None, document: list[Any] | None) -> str:
    model = normalize_decision_model(stored)
    if model and model in set(openrouter_model_ids(document)):
        return model
    return ""


def reconcile_decision_model(
    stored: str | None,
    document: list[Any] | None,
) -> tuple[str, str | None]:
    model = normalize_decision_model(stored)
    resolved = effective_decision_model(model, document)
    if model and not resolved:
        return "", DECISION_MODEL_CLEARED_WARNING
    return resolved, None


def omit_decision_model_from_document(
    document: list[Any] | None,
    decision_model: str | None,
) -> list[Any] | None:
    if document is None:
        return None
    model_id = normalize_decision_model(decision_model)
    result = copy.deepcopy(document)
    if not model_id:
        return result
    for provider in result:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        provider["models"] = [
            model
            for model in models
            if not (isinstance(model, dict) and model.get("id") == model_id)
        ]
    return result
