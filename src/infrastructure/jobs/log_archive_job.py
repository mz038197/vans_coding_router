from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any


async def run_archive_once(
    repo: Any,
    now: datetime | None = None,
    archive_after_days: int | None = None,
    delete_after_days: int | None = None,
) -> dict[str, Any]:
    archived = await asyncio.to_thread(
        repo.archive_prompt_logs,
        now=now,
        archive_after_days=archive_after_days,
    )
    purged = await asyncio.to_thread(
        repo.purge_archived_prompt_logs,
        now=now,
        delete_after_days=delete_after_days,
    )
    sessions_deleted = await asyncio.to_thread(repo.purge_portal_sessions, now=now)
    return {
        "archived": archived.get("archived", 0),
        "deleted": purged.get("deleted", 0),
        "portal_sessions_deleted": sessions_deleted,
    }


async def run_daily_archive_job(repo: Any, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await run_archive_once(
            repo,
            archive_after_days=repo.settings.prompt_logs.archive_after_days,
            delete_after_days=repo.settings.prompt_logs.delete_after_days,
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timedelta(days=1).total_seconds())
        except TimeoutError:
            continue
