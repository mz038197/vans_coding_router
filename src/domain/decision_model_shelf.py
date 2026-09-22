from __future__ import annotations

import json

DECISION_MODEL_SHELF = (
    "openrouter@typesafe/jev-1.13",
    "openrouter@~typesafe/jev-latest",
)


def is_decision_model_id(model_id: str) -> bool:
    return model_id in DECISION_MODEL_SHELF


def parse_decision_model_allowlist_json(raw: str | None) -> list[str]:
    if raw is None or raw == "":
        return []
    data = json.loads(raw)
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError("決策模型允許清單格式錯誤")
    return list(data)


def dump_decision_model_allowlist_json(allowlist: list[str]) -> str:
    return json.dumps(allowlist, ensure_ascii=False)


def validate_decision_model_allowlist(allowlist: list[str]) -> list[str]:
    if not isinstance(allowlist, list) or not all(isinstance(item, str) for item in allowlist):
        raise ValueError("決策模型允許清單格式錯誤")
    unknown = [model_id for model_id in allowlist if model_id not in DECISION_MODEL_SHELF]
    if unknown:
        raise ValueError(f"模型不在決策模型架子：{unknown[0]}")
    seen: set[str] = set()
    unique: list[str] = []
    for model_id in allowlist:
        if model_id not in seen:
            seen.add(model_id)
            unique.append(model_id)
    return unique
