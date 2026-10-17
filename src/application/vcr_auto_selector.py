"""The vcr-auto Selector: one Decision Request that picks an Auto Tier (ADR-0037)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.application.vcr_auto_walk import VcrAutoWalk
from src.domain.auto_tier import (
    AutoTier,
    TierSelection,
    selector_decision_body,
    strongest_plausible,
)
from src.domain.ports.llm_gateway import LLMGatewayPort

logger = logging.getLogger(__name__)

SELECTOR_TIMEOUT_SECONDS = 1.5


class VcrAutoSelector:
    def __init__(self, gateway: LLMGatewayPort, *, timeout: float = SELECTOR_TIMEOUT_SECONDS):
        self.gateway = gateway
        self.timeout = timeout

    async def select(
        self,
        selector_ids: list[str],
        tiers: list[AutoTier],
        state: str,
    ) -> TierSelection | None:
        """The chosen tier, or None when the selector errs, refuses, or is too slow.

        A failure only means document order: it is logged at INFO, never raised.
        """
        walker = VcrAutoWalk()

        async def call(model_id: str) -> dict[str, Any]:
            return await self.gateway.decisions_create(selector_decision_body(model_id, state, tiers))

        try:
            hit = await asyncio.wait_for(walker.run(selector_ids, call), self.timeout)
            selection = strongest_plausible(tiers, hit.value)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - selection only reorders a walk that works without it
            logger.info("vcr_auto_selector_failed: %s", type(exc).__name__)
            return None
        if selection is None:
            logger.info("vcr_auto_selector_failed: unreadable answer")
        return selection
