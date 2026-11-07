"""The editor draft after a teacher uploads a model list file (#70, ADR-0037).

- Every uploaded Model ID lands on the text shelf; shelf flags in the file are dropped.
- The file's ``autoTiers`` replace the draft's when the file has them and they pass the
  save check's tier rules; otherwise the draft keeps its tiers.
- A model keeps its ``autoTier`` when the resulting tiers name it.
- The file's ``selectorShelf`` is never taken; the draft keeps its own, just as an upload
  cannot fill the decision shelf.
"""

from __future__ import annotations

import copy
from typing import Any

from src.domain.auto_tier import AUTO_TIER_KEY, AUTO_TIERS_KEY, SELECTOR_SHELF_KEY, auto_tiers
from src.domain.auto_tier_save_check import check_auto_tiers
from src.domain.model_shelf import ROUTER_ONLY_DOCUMENT_KEYS, SHELF_KEYS
from src.domain.session_model_allowlist import normalize_session_chat_language_models


def uploaded_model_document(current: Any, uploaded: Any) -> list[dict[str, Any]]:
    """The new draft: ``current`` is the open draft, ``uploaded`` the file. Raises ValueError."""
    if not isinstance(uploaded, list) or not all(isinstance(p, dict) for p in uploaded):
        raise ValueError("必須是一個 VCRouter customendpoint 提供者陣列")
    draft = normalize_session_chat_language_models(current if isinstance(current, list) else [])[0]

    kept: dict[str, Any] = {}
    file_tiers = next((p[AUTO_TIERS_KEY] for p in uploaded if AUTO_TIERS_KEY in p), None)
    if file_tiers is not None:
        check_auto_tiers(file_tiers)
        kept[AUTO_TIERS_KEY] = copy.deepcopy(file_tiers)
    elif AUTO_TIERS_KEY in draft:
        kept[AUTO_TIERS_KEY] = draft[AUTO_TIERS_KEY]
    if SELECTOR_SHELF_KEY in draft:
        kept[SELECTOR_SHELF_KEY] = draft[SELECTOR_SHELF_KEY]

    providers: list[dict[str, Any]] = [{**kept, "models": []}]
    for provider in copy.deepcopy(uploaded):
        for key in ROUTER_ONLY_DOCUMENT_KEYS:
            provider.pop(key, None)
        for model in provider.get("models") or []:
            if isinstance(model, dict):
                for key in SHELF_KEYS:
                    model.pop(key, None)
        providers.append(provider)

    document = normalize_session_chat_language_models(providers)
    tier_ids = {tier.id for tier in auto_tiers(document)}
    for model in document[0]["models"]:
        if model.get(AUTO_TIER_KEY) not in tier_ids:
            model.pop(AUTO_TIER_KEY, None)
    return document
