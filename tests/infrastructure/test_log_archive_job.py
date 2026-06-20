from datetime import UTC, datetime

import pytest

from src.infrastructure.jobs.log_archive_job import run_archive_once


@pytest.mark.asyncio
async def test_run_archive_once_calls_repository_archive():
    class Repo:
        def __init__(self):
            self.called_with = None

        def archive_prompt_logs(self, now=None, retention_days=None):
            self.called_with = {"now": now, "retention_days": retention_days}
            return {"archived": 3}

    repo = Repo()
    now = datetime(2026, 6, 18, tzinfo=UTC)

    result = await run_archive_once(repo, now=now, retention_days=7)

    assert result == {"archived": 3}
    assert repo.called_with == {"now": now, "retention_days": 7}

