from __future__ import annotations

import copy
import json
from typing import Any

MODEL_ALLOWLIST_UNCHANGED = object()


def template_model_ids(template: list[Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for provider in template:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = model.get("id")
            if isinstance(model_id, str) and model_id and model_id not in seen:
                seen.add(model_id)
                ids.append(model_id)
    return ids


def parse_allowlist_json(raw: str | None) -> list[str] | None:
    if raw is None or raw == "":
        return None
    data = json.loads(raw)
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError("模型允許清單格式錯誤")
    return list(data)


def dump_allowlist_json(allowlist: list[str] | None) -> str | None:
    if allowlist is None:
        return None
    return json.dumps(allowlist, ensure_ascii=False)


def parse_session_chat_language_models_json(raw: str | None) -> list[Any] | None:
    if raw is None or raw == "":
        return None
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Session Chat Language Models 格式錯誤")
    return data


def dump_session_chat_language_models_json(document: list[Any] | None) -> str | None:
    if document is None:
        return None
    return json.dumps(document, ensure_ascii=False)


def allowlist_from_document(document: list[Any] | None) -> list[str] | None:
    if document is None:
        return None
    return template_model_ids(document)


def validate_allowlist(allowlist: list[str], template: list[Any]) -> list[str]:
    allowed = set(template_model_ids(template))
    unknown = [model_id for model_id in allowlist if model_id not in allowed]
    if unknown:
        raise ValueError(f"模型不在 Router Model Template：{unknown[0]}")
    seen: set[str] = set()
    unique: list[str] = []
    for model_id in allowlist:
        if model_id not in seen:
            seen.add(model_id)
            unique.append(model_id)
    return unique


def filter_chat_language_models(
    template: list[Any],
    allowlist: list[str] | None,
) -> list[Any]:
    result = copy.deepcopy(template)
    if allowlist is None:
        return result
    allowed = set(allowlist)
    for provider in result:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        provider["models"] = [
            model
            for model in models
            if isinstance(model, dict) and model.get("id") in allowed
        ]
    return result


def is_model_allowed(model_id: str, allowlist: list[str] | None) -> bool:
    if allowlist is None:
        return True
    return model_id in set(allowlist)
