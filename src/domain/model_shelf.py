from __future__ import annotations

import copy
from typing import Any

from src.domain.decision_model import is_decision_shelf_model

IMAGE_SHELF_KEY = "imageShelf"
SPEECH_SHELF_KEY = "speechShelf"
SPEECH_TRANSCRIPTION_SHELF_KEY = "speechTranscriptionShelf"
SHELF_KEYS = (
    "decisionShelf",
    IMAGE_SHELF_KEY,
    SPEECH_SHELF_KEY,
    SPEECH_TRANSCRIPTION_SHELF_KEY,
)


def enforce_single_shelf(model: dict[str, Any]) -> None:
    active = [key for key in SHELF_KEYS if model.get(key) is True]
    if len(active) > 1:
        raise ValueError("一個 Model ID 只能屬於一個架")
    for key in SHELF_KEYS:
        if model.get(key) is not True:
            model.pop(key, None)


def is_image_shelf_model(model: Any) -> bool:
    return _is_flagged_model(model, IMAGE_SHELF_KEY)


def is_speech_shelf_model(model: Any) -> bool:
    return _is_flagged_model(model, SPEECH_SHELF_KEY)


def is_speech_transcription_shelf_model(model: Any) -> bool:
    return _is_flagged_model(model, SPEECH_TRANSCRIPTION_SHELF_KEY)


def is_non_text_shelf_model(model: Any) -> bool:
    return (
        is_decision_shelf_model(model)
        or is_image_shelf_model(model)
        or is_speech_shelf_model(model)
        or is_speech_transcription_shelf_model(model)
    )


def shelf_model_ids(document: list[Any] | None, shelf_key: str) -> list[str]:
    predicate = {
        "decisionShelf": is_decision_shelf_model,
        IMAGE_SHELF_KEY: is_image_shelf_model,
        SPEECH_SHELF_KEY: is_speech_shelf_model,
        SPEECH_TRANSCRIPTION_SHELF_KEY: is_speech_transcription_shelf_model,
    }.get(shelf_key)
    if predicate is None:
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for provider in document or []:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not predicate(model):
                continue
            model_id = model["id"]
            if model_id in seen:
                continue
            seen.add(model_id)
            ids.append(model_id)
    return ids


def omit_non_text_shelf_models(document: list[Any] | None) -> list[Any] | None:
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
            model for model in models if not is_non_text_shelf_model(model)
        ]
    return result


def _is_flagged_model(model: Any, shelf_key: str) -> bool:
    return (
        isinstance(model, dict)
        and model.get(shelf_key) is True
        and isinstance(model.get("id"), str)
        and bool(model["id"])
    )

