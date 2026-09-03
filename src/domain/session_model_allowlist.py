from __future__ import annotations

import copy
import json
from typing import Any

MODEL_ALLOWLIST_UNCHANGED = object()
SESSION_CHAT_LANGUAGE_MODELS_UNCHANGED = object()

VCROUTER_STENCIL: dict[str, Any] = {
    "name": "VCRouter",
    "vendor": "customendpoint",
    "apiKey": "",
    "apiType": "responses",
    "url": "https://ai.vanscoding.com/v1",
    "requestHeaders": {"Authorization": "Bearer ${apiKey}"},
    "thinking": True,
    "reasoningEffortFormat": "responses",
    "supportsReasoningEffort": ["none", "low", "medium", "high"],
    "zeroDataRetentionEnabled": True,
    "toolCalling": True,
    "vision": True,
    "maxInputTokens": 262144,
    "maxOutputTokens": 65536,
}


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


def default_vcrouter_model(model_id: str, display_name: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": display_name,
        "url": VCROUTER_STENCIL["url"],
        "requestHeaders": copy.deepcopy(VCROUTER_STENCIL["requestHeaders"]),
        "thinking": VCROUTER_STENCIL["thinking"],
        "reasoningEffortFormat": VCROUTER_STENCIL["reasoningEffortFormat"],
        "supportsReasoningEffort": list(VCROUTER_STENCIL["supportsReasoningEffort"]),
        "zeroDataRetentionEnabled": VCROUTER_STENCIL["zeroDataRetentionEnabled"],
        "toolCalling": VCROUTER_STENCIL["toolCalling"],
        "vision": VCROUTER_STENCIL["vision"],
        "maxInputTokens": VCROUTER_STENCIL["maxInputTokens"],
        "maxOutputTokens": VCROUTER_STENCIL["maxOutputTokens"],
    }


def normalize_session_chat_language_models(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, list):
        raise ValueError("Session Chat Language Models 必須是陣列")
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider in document:
        if not isinstance(provider, dict):
            raise ValueError("Session Chat Language Models 必須是一個 VCRouter customendpoint 提供者")
        models = provider.get("models")
        if models is None:
            continue
        if not isinstance(models, list):
            raise ValueError("Session Chat Language Models 格式錯誤")
        for model in models:
            if not isinstance(model, dict):
                raise ValueError("Session Chat Language Models 格式錯誤")
            model_id = model.get("id")
            if not isinstance(model_id, str) or not model_id.strip():
                raise ValueError("模型缺少 id")
            if model_id in seen:
                continue
            seen.add(model_id)
            restenciled = dict(model)
            restenciled["id"] = model_id
            restenciled["url"] = VCROUTER_STENCIL["url"]
            restenciled["requestHeaders"] = copy.deepcopy(VCROUTER_STENCIL["requestHeaders"])
            collected.append(restenciled)
    return [
        {
            "name": VCROUTER_STENCIL["name"],
            "vendor": VCROUTER_STENCIL["vendor"],
            "apiKey": VCROUTER_STENCIL["apiKey"],
            "apiType": VCROUTER_STENCIL["apiType"],
            "models": collected,
        }
    ]
