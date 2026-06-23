from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any


async def run_archive_once(repo: Any, now: datetime | None = None, retention_days: int | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(
        repo.archive_prompt_logs,
        now=now,
        retention_days=retention_days,
    )


async def run_daily_archive_job(repo: Any, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        retention_days = repo.settings.prompt_logs.retention_days
        await run_archive_once(repo, retention_days=retention_days)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timedelta(days=1).total_seconds())
        except TimeoutError:
            continue
