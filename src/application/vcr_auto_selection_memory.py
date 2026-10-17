"""One question, one selection: the vcr-auto Selector's choice, remembered (ADR-0037, #66).

A Copilot agent calls the router several times for one question, each time with the
same last user message. Those calls reuse the first selection, so the walk does not
change model mid-task and the selector is asked once.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Callable

from src.domain.auto_tier import AutoTier, TierSelection

SELECTION_MEMORY_SECONDS = 30 * 60.0


class VcrAutoSelectionMemory:
    """Selections keyed by API key, last user message, and the document's tier fingerprint.

    ``tiers`` is every Auto Tier of the document, including tiers that hold no Model ID.
    The fingerprint covers their ids, names, descriptions, and order, so a teacher's edit
    to any of them asks the selector again. The memory lives in this process and
    resets on restart.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = SELECTION_MEMORY_SECONDS,
    ):
        self._clock = clock
        self._ttl = ttl
        self._selections: dict[str, tuple[float, TierSelection]] = {}

    def recall(self, api_key: str, last_user_text: str, tiers: list[AutoTier]) -> TierSelection | None:
        key = _key(api_key, last_user_text, tiers)
        entry = self._selections.get(key)
        if entry is None:
            return None
        stored_at, selection = entry
        if self._clock() - stored_at >= self._ttl:
            del self._selections[key]
            return None
        return selection

    def remember(
        self,
        api_key: str,
        last_user_text: str,
        tiers: list[AutoTier],
        selection: TierSelection,
    ) -> None:
        now = self._clock()
        self._selections = {
            key: entry for key, entry in self._selections.items() if now - entry[0] < self._ttl
        }
        self._selections[_key(api_key, last_user_text, tiers)] = (now, selection)


def _key(api_key: str, last_user_text: str, tiers: list[AutoTier]) -> str:
    material = json.dumps(
        [api_key, last_user_text, [[tier.id, tier.name, tier.description] for tier in tiers]],
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
