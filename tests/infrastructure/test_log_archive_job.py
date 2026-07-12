from datetime import UTC, datetime

import pytest

from src.infrastructure.jobs.log_archive_job import run_archive_once


@pytest.mark.asyncio
async def test_run_archive_once_calls_repository_archive_and_purge():
    class Repo:
        def __init__(self):
            self.archive_called_with = None
            self.purge_called_with = None

        def archive_prompt_logs(self, now=None, archive_after_days=None):
            self.archive_called_with = {"now": now, "archive_after_days": archive_after_days}
            return {"archived": 3}

        def purge_archived_prompt_logs(self, now=None, delete_after_days=None):
            self.purge_called_with = {"now": now, "delete_after_days": delete_after_days}
            return {"deleted": 2}

    repo = Repo()
    now = datetime(2026, 6, 18, tzinfo=UTC)

    result = await run_archive_once(repo, now=now, archive_after_days=15, delete_after_days=30)

    assert result == {"archived": 3, "deleted": 2}
    assert repo.archive_called_with == {"now": now, "archive_after_days": 15}
    assert repo.purge_called_with == {"now": now, "delete_after_days": 30}
