"""Refresh the in-process Upstream Model Catalog."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.application.upstream_model_catalog import CATALOG_REFRESH_INTERVAL_SEC

logger = logging.getLogger(__name__)


async def fill_catalog_round(portal: Any) -> None:
    """One Upstream Model Catalog round. A throw logs the existing error and propagates."""
    try:
        await portal.fill_upstream_model_catalog()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Upstream Model Catalog refresh failed")
        raise


async def run_upstream_model_catalog_refresh(
    portal: Any,
    stop_event: asyncio.Event,
    interval_sec: float = CATALOG_REFRESH_INTERVAL_SEC,
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
        except TimeoutError:
            try:
                await fill_catalog_round(portal)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
        except asyncio.CancelledError:
            raise
