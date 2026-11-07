"""Process memory for the Upstream Model Catalog."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Any, Callable

from src.domain.errors import UpstreamServiceError, UpstreamTransportError
from src.infrastructure.config import RouterSettings, provider_has_kind_split

logger = logging.getLogger(__name__)

CATALOG_FETCH_TIMEOUT_SEC = 30.0
CATALOG_FETCH_BUDGET_SEC = 45.0
CATALOG_RETRY_DELAYS_SEC = (2.0, 5.0)
CATALOG_REFRESH_INTERVAL_SEC = 30 * 60
FAILURE_BODY_LIMIT = 500

# Teacher kind → upstream output_modalities query for a provider with a kind split.
KIND_SPLIT_MODALITIES = {
    "text": "text",
    "decisions": "decisions",
    "image": "image",
    "embeddings": "embeddings",
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
        fetch_budget_sec: float = CATALOG_FETCH_BUDGET_SEC,
        retry_delays_sec: tuple[float, ...] = CATALOG_RETRY_DELAYS_SEC,
    ):
        self._settings = settings_fn
        self._gateway = gateway
        self._fetch_timeout_sec = fetch_timeout_sec
        self._fetch_budget_sec = fetch_budget_sec
        self._retry_delays_sec = retry_delays_sec
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
        failed: list[tuple[str, str]] = []
        seen: set[str] = set()
        for provider, kind, models, reason in results:
            if models is None:
                if provider not in seen:
                    seen.add(provider)
                    label = provider if kind is None else f"{provider} {kind}"
                    failed.append((provider, f"{label}: {reason}"))
                continue
            updated[(provider, kind)] = models
        self._snapshots = updated
        if failed:
            names = ", ".join(name for name, _reason in failed)
            reasons = "\n\n".join(reason for _name, reason in failed)
            logger.error(f"Upstream Model Catalog round did not update: {names}\n{reasons}")

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
    ) -> tuple[str, str | None, list[dict[str, Any]] | None, str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._fetch_budget_sec
        delays = list(self._retry_delays_sec)
        while True:
            try:
                raw = await asyncio.wait_for(
                    self._fetch_raw(provider, modality),
                    timeout=min(self._fetch_timeout_sec, deadline - loop.time()),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                retry = (
                    _is_transient(exc)
                    and bool(delays)
                    and loop.time() + delays[0] < deadline
                )
                logger.warning(
                    "Upstream Model Catalog fetch failed: provider=%s kind=%s retry=%s",
                    provider,
                    kind or "all",
                    retry,
                    exc_info=True,
                )
                if retry:
                    await asyncio.sleep(delays.pop(0))
                    continue
                return provider, kind, None, _failure_reason(exc)
            models = _accepted_models(raw, provider)
            if models is None:
                return provider, kind, None, f"unusable model list: {_cut(raw)}"
            return provider, kind, models, ""

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


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (UpstreamTransportError, TimeoutError)):
        return True
    if isinstance(exc, UpstreamServiceError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, UpstreamServiceError):
        body = (exc.details or {}).get("body")
        return f"HTTP {exc.status_code}: {_cut(body)}"
    return traceback.format_exc()


def _cut(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:FAILURE_BODY_LIMIT]


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
