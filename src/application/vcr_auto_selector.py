"""The vcr-auto Selector: one Decision Request that picks an Auto Tier (ADR-0037)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SelectorAnswer:
    """What one selector question produced.

    selection: the chosen tier, or None when the selector errs, refuses, is too slow,
    or answers unreadably.
    model_id / usage: the Selector Model ID that replied and the reply's raw usage
    block, set whenever a reply arrived, even an unreadable one (ADR-0097). A timeout
    or an upstream failure leaves them None.
    """

    selection: TierSelection | None
    model_id: str | None = None
    usage: dict[str, Any] | None = None


class VcrAutoSelector:
    def __init__(self, gateway: LLMGatewayPort, *, timeout: float = SELECTOR_TIMEOUT_SECONDS):
        self.gateway = gateway
        self.timeout = timeout

    async def select(
        self,
        selector_ids: list[str],
        tiers: list[AutoTier],
        state: str,
    ) -> SelectorAnswer:
        """The chosen tier and the reply's spend; failure only means document order.

        A failure is logged at INFO, never raised.
        """
        walker = VcrAutoWalk()

        async def call(model_id: str) -> dict[str, Any]:
            return await self.gateway.decisions_create(selector_decision_body(model_id, state, tiers))

        try:
            hit = await asyncio.wait_for(walker.run(selector_ids, call), self.timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - selection only reorders a walk that works without it
            logger.info("vcr_auto_selector_failed: %s", type(exc).__name__)
            return SelectorAnswer(selection=None)
        reply = hit.value if isinstance(hit.value, dict) else {}
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else None
        selection = strongest_plausible(tiers, hit.value)
        if selection is None:
            logger.info("vcr_auto_selector_failed: unreadable answer")
        return SelectorAnswer(selection=selection, model_id=hit.model_id, usage=usage)
