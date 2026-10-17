"""Save checks for Auto Tiers and the selector shelf (ADR-0037).

One check for both saves: a sitting's Session Chat Language Models and a Router Model
Template. It reads the document after ``normalize_session_chat_language_models``, so a
non-text-shelf model already carries no ``autoTier``.
"""

from __future__ import annotations

from typing import Any

from src.domain.auto_tier import (
    AUTO_TIER_KEY,
    AUTO_TIERS_KEY,
    SELECTOR_SHELF_KEY,
    auto_tiers,
    selector_shelf_ids,
)
from src.domain.model_shelf import is_non_text_shelf_model

TIER_COUNT_MIN = 2
TIER_COUNT_MAX = 6
TIER_NAME_LIMIT = 20
TIER_DESCRIPTION_LIMIT = 300


def check_auto_tier_document(
    document: list[Any],
    *,
    previous: list[Any] | None,
    decision_list_ids: set[str],
) -> None:
    """Refuse a save that breaks a tier or selector-shelf rule. Raises ValueError with the reason.

    ``previous`` is the stored document this save replaces: it names a deleted tier, and
    its selector-shelf ids stay accepted when the decisions list no longer shows them.
    ``decision_list_ids`` is what the OpenRouter decisions list shows now.
    """
    for provider in _providers(document):
        _check_tiers(provider.get(AUTO_TIERS_KEY))
        _check_selector_shelf_shape(provider.get(SELECTOR_SHELF_KEY))

    tier_ids = {tier.id for tier in auto_tiers(document)}
    previous_names = {tier.id: tier.name for tier in auto_tiers(previous)}
    for model in _models(document):
        if AUTO_TIER_KEY not in model or model[AUTO_TIER_KEY] in tier_ids:
            continue
        tier_id = model[AUTO_TIER_KEY]
        if isinstance(tier_id, str) and tier_id in previous_names:
            raise ValueError(
                f"Tier「{previous_names[tier_id]}」還有 Model ID，不能刪除：{model['id']}"
            )
        raise ValueError(f"Model ID {model['id']} 的 Tier 不存在")

    selector = selector_shelf_ids(document)
    already_stored = set(selector_shelf_ids(previous))
    for model_id in selector:
        if model_id not in already_stored and model_id not in decision_list_ids:
            raise ValueError(f"自動選模架只接受 OpenRouter 決策清單的 Model ID：{model_id}")

    if selector:
        for model in _models(document):
            if not is_non_text_shelf_model(model) and AUTO_TIER_KEY not in model:
                raise ValueError(
                    f"自動選模架有 Model ID 時，每個對話模型都要有 Tier：{model['id']}"
                )


def _check_tiers(raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ValueError("Tier 格式錯誤")
    if raw and not TIER_COUNT_MIN <= len(raw) <= TIER_COUNT_MAX:
        raise ValueError(f"Tier 數量必須是 {TIER_COUNT_MIN} 到 {TIER_COUNT_MAX} 個")
    ids: set[str] = set()
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Tier 格式錯誤")
        tier_id, name, description = item.get("id"), item.get("name"), item.get("description")
        if not isinstance(tier_id, str) or not tier_id.strip():
            raise ValueError("Tier 缺少 id")
        if tier_id in ids:
            raise ValueError(f"Tier id「{tier_id}」重複")
        ids.add(tier_id)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tier 名稱不可空白")
        if len(name) > TIER_NAME_LIMIT:
            raise ValueError(f"Tier 名稱不可超過 {TIER_NAME_LIMIT} 字：{name}")
        if name in names:
            raise ValueError(f"Tier 名稱「{name}」重複")
        names.add(name)
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Tier「{name}」的說明不可空白")
        if len(description) > TIER_DESCRIPTION_LIMIT:
            raise ValueError(f"Tier「{name}」的說明不可超過 {TIER_DESCRIPTION_LIMIT} 字")


def _check_selector_shelf_shape(raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, list) or not all(
        isinstance(model_id, str) and model_id.strip() for model_id in raw
    ):
        raise ValueError("自動選模架格式錯誤")


def _providers(document: list[Any] | None) -> list[dict[str, Any]]:
    return [provider for provider in document or [] if isinstance(provider, dict)]


def _models(document: list[Any] | None) -> list[dict[str, Any]]:
    return [
        model
        for provider in _providers(document)
        if isinstance(provider.get("models"), list)
        for model in provider["models"]
        if isinstance(model, dict)
    ]
