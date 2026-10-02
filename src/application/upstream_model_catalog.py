"""Process memory for the Upstream Model Catalog."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from src.infrastructure.config import RouterSettings, provider_has_kind_split

logger = logging.getLogger(__name__)

CATALOG_FETCH_TIMEOUT_SEC = 30.0
CATALOG_REFRESH_INTERVAL_SEC = 30 * 60

# Teacher kind → upstream output_modalities query for a provider with a kind split.
KIND_SPLIT_MODALITIES = {
    "text": "text",
    "decisions": "decisions",
    "image": "image",
    "speech": "speech",
    "speech_transcription": "transcription",
}


class UpstreamModelCatalogMemory:
    """Snapshots of enabled providers. A failed fetch leaves the previous snapshot."""

    def __init__(
        self,
        settings_fn: Callable[[], RouterSettings],
        gateway: Any | None,
        *,
        fetch_timeout_sec: float = CATALOG_FETCH_TIMEOUT_SEC,
    ):
        self._settings = settings_fn
        self._gateway = gateway
        self._fetch_timeout_sec = fetch_timeout_sec
        self._snapshots: dict[tuple[str, str | None], list[dict[str, Any]]] = {}

    async def fill(self) -> None:
        if self._gateway is None:
            return
        kind_split, all_models = self._provider_groups()
        tasks = [
            asyncio.create_task(self._fetch_one(name, kind, modality))
            for name in kind_split
            for kind, modality in KIND_SPLIT_MODALITIES.items()
        ]
        tasks.extend(
            asyncio.create_task(self._fetch_one(name, None, None))
            for name in all_models
        )
        if not tasks:
            return
        results = await asyncio.gather(*tasks)
        updated = dict(self._snapshots)
        for provider, kind, models in results:
            if models is None:
                continue
            updated[(provider, kind)] = models
        self._snapshots = updated

    def read(self, requested: str) -> dict[str, Any]:
        kind_split, all_models_providers = self._provider_groups()
        if requested == "all":
            providers = all_models_providers
            kind: str | None = None
        else:
            providers = kind_split
            kind = requested
        snapshots = self._snapshots
        models: list[dict[str, Any]] = []
        failed: list[str] = []
        for name in providers:
            snapshot = snapshots.get((name, kind))
            if snapshot is None:
                failed.append(name)
                continue
            models.extend(dict(item) for item in snapshot)
        unavailable = bool(providers) and not models and set(providers) <= set(failed)
        return {
            "providers": providers,
            "models": models,
            "unavailable": unavailable,
            "all_models_providers": all_models_providers,
            "kind_split_providers": kind_split,
        }

    def _provider_groups(self) -> tuple[list[str], list[str]]:
        enabled = [
            name
            for name, provider in self._settings().providers.items()
            if provider.enabled
        ]
        kind_split = [name for name in enabled if provider_has_kind_split(name)]
        all_models = [name for name in enabled if name not in kind_split]
        return kind_split, all_models

    async def _fetch_one(
        self,
        provider: str,
        kind: str | None,
        modality: str | None,
    ) -> tuple[str, str | None, list[dict[str, Any]] | None]:
        try:
            raw = await asyncio.wait_for(
                self._fetch_raw(provider, modality),
                timeout=self._fetch_timeout_sec,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Upstream Model Catalog fetch failed: provider=%s kind=%s",
                provider,
                kind or "all",
                exc_info=True,
            )
            return provider, kind, None
        return provider, kind, _accepted_models(raw, provider)

    async def _fetch_raw(self, provider: str, modality: str | None) -> Any:
        one = getattr(self._gateway, "provider_models", None)
        if callable(one):
            return await one(provider, output_modalities=modality)
        models_fn = getattr(self._gateway, "models", None)
        if not callable(models_fn):
            raise RuntimeError("models catalog unavailable")
        if modality:
            return await models_fn(output_modalities=modality)
        return await models_fn()


def _accepted_models(raw: Any, provider: str) -> list[dict[str, Any]] | None:
    if not isinstance(raw, dict):
        return None
    errors = raw.get("provider_errors") or {}
    models: list[dict[str, Any]] = []
    for item in raw.get("data") or []:
        if not isinstance(item, dict):
            continue
        item_provider = item.get("provider")
        if item_provider not in (None, provider):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        name = item.get("name")
        models.append(
            {
                "id": model_id,
                "provider": provider,
                "name": name if isinstance(name, str) and name else model_id,
            }
        )
    if provider in errors and not models:
        return None
    return models
