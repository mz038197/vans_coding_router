import asyncio

import pytest

from src.domain.errors import UpstreamBusyError
from src.infrastructure.gateways.upstream_key_pool import UpstreamKeyPool


@pytest.mark.asyncio
async def test_least_in_flight_spreads_across_keys():
    pool = UpstreamKeyPool(["key-a", "key-b"], max_concurrent_per_key=0, acquire_delay_ms=0)
    first = await pool.acquire()
    second = await pool.acquire()
    assert {first, second} == {0, 1}
    assert pool.in_flight_snapshot() == [1, 1]
    await pool.release(first)
    await pool.release(second)
    assert pool.in_flight_snapshot() == [0, 0]


@pytest.mark.asyncio
async def test_prefers_less_loaded_key_after_release():
    pool = UpstreamKeyPool(["key-a", "key-b"], max_concurrent_per_key=0, acquire_delay_ms=0)
    a = await pool.acquire()
    b = await pool.acquire()
    await pool.release(a)
    again = await pool.acquire()
    assert again == a
    await pool.release(b)
    await pool.release(again)


@pytest.mark.asyncio
async def test_waits_until_slot_available():
    pool = UpstreamKeyPool(
        ["key-a", "key-b"],
        max_concurrent_per_key=1,
        queue_timeout_sec=2,
        acquire_delay_ms=0,
    )
    first = await pool.acquire()
    second = await pool.acquire()
    assert {first, second} == {0, 1}

    waiter = asyncio.create_task(pool.acquire())
    await asyncio.sleep(0.05)
    assert not waiter.done()

    await pool.release(first)
    third = await asyncio.wait_for(waiter, timeout=1)
    assert third == first
    await pool.release(second)
    await pool.release(third)


@pytest.mark.asyncio
async def test_queue_timeout_raises_upstream_busy():
    pool = UpstreamKeyPool(
        ["key-a"],
        max_concurrent_per_key=1,
        queue_timeout_sec=0.05,
        acquire_delay_ms=0,
    )
    held = await pool.acquire()
    with pytest.raises(UpstreamBusyError) as exc_info:
        await pool.acquire()
    assert "busy" in exc_info.value.message.lower()
    assert exc_info.value.code == "upstream_busy"
    assert pool.in_flight_snapshot() == [1]
    assert pool.status()["busy_total"] == 1
    await pool.release(held)
    assert pool.in_flight_snapshot() == [0]


@pytest.mark.asyncio
async def test_status_reports_in_flight_waiting_and_capacity():
    pool = UpstreamKeyPool(
        ["key-a", "key-b"],
        max_concurrent_per_key=1,
        queue_timeout_sec=2,
        acquire_delay_ms=0,
    )
    first = await pool.acquire()
    second = await pool.acquire()
    waiter = asyncio.create_task(pool.acquire())
    await asyncio.sleep(0.05)
    status = pool.status()
    assert status["key_count"] == 2
    assert status["max_concurrent_per_key"] == 1
    assert status["capacity"] == 2
    assert status["in_flight_total"] == 2
    assert status["waiting"] == 1
    assert status["busy_total"] == 0
    assert status["keys"] == [
        {
            "index": 0,
            "in_flight": 1,
            "cap": 1,
            "quarantined": False,
            "quarantine_remaining_sec": None,
        },
        {
            "index": 1,
            "in_flight": 1,
            "cap": 1,
            "quarantined": False,
            "quarantine_remaining_sec": None,
        },
    ]
    assert "key-a" not in str(status)

    await pool.release(first)
    third = await asyncio.wait_for(waiter, timeout=1)
    assert pool.status()["waiting"] == 0
    await pool.release(second)
    await pool.release(third)


@pytest.mark.asyncio
async def test_acquire_rolls_back_slot_if_cancelled_during_delay():
    pool = UpstreamKeyPool(
        ["key-a"],
        max_concurrent_per_key=1,
        queue_timeout_sec=1,
        acquire_delay_ms=500,
    )
    task = asyncio.create_task(pool.acquire())
    await asyncio.sleep(0.05)
    assert pool.in_flight_snapshot() == [1]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert pool.in_flight_snapshot() == [0]
    # Delay is still 500ms on this pool; allow enough time to finish acquire.
    recovered = await asyncio.wait_for(pool.acquire(), timeout=1.0)
    await pool.release(recovered)
    assert pool.in_flight_snapshot() == [0]


@pytest.mark.asyncio
async def test_release_completes_accounting_when_caller_cancelled():
    pool = UpstreamKeyPool(["key-a"], max_concurrent_per_key=1, acquire_delay_ms=0)
    index = await pool.acquire()
    assert pool.in_flight_snapshot() == [1]

    async def release_and_hang():
        await pool.release(index)
        await asyncio.sleep(10)

    task = asyncio.create_task(release_and_hang())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert pool.in_flight_snapshot() == [0]


@pytest.mark.asyncio
async def test_quarantine_skips_key_on_acquire():
    pool = UpstreamKeyPool(
        ["key-a", "key-b"],
        max_concurrent_per_key=0,
        acquire_delay_ms=0,
        quarantine_ttl_sec=3600,
    )
    pool.quarantine(0, "extra usage balance is empty")
    index = await pool.acquire()
    assert index == 1
    assert pool.last_extra_usage_message == "extra usage balance is empty"
    status = pool.status()
    assert status["keys"][0]["quarantined"] is True
    assert status["keys"][0]["quarantine_remaining_sec"] is not None
    assert status["keys"][0]["quarantine_remaining_sec"] > 0
    assert status["keys"][1]["quarantined"] is False
    await pool.release(index)


@pytest.mark.asyncio
async def test_acquire_exclude_skips_tried_keys():
    pool = UpstreamKeyPool(["key-a", "key-b"], max_concurrent_per_key=0, acquire_delay_ms=0)
    first = await pool.acquire(exclude=frozenset({0}))
    assert first == 1
    await pool.release(first)


@pytest.mark.asyncio
async def test_all_quarantined_acquire_raises_immediately():
    from src.infrastructure.gateways.upstream_key_pool import NoSelectableUpstreamKeyError

    pool = UpstreamKeyPool(
        ["key-a", "key-b"],
        max_concurrent_per_key=0,
        acquire_delay_ms=0,
        quarantine_ttl_sec=3600,
    )
    pool.quarantine(0, "extra usage on a")
    pool.quarantine(1, "extra usage on b")
    with pytest.raises(NoSelectableUpstreamKeyError):
        await pool.acquire()
    assert pool.last_extra_usage_message == "extra usage on b"


@pytest.mark.asyncio
async def test_release_quarantine_makes_key_selectable():
    from src.infrastructure.gateways.upstream_key_pool import NoSelectableUpstreamKeyError

    pool = UpstreamKeyPool(
        ["key-a"],
        max_concurrent_per_key=0,
        acquire_delay_ms=0,
        quarantine_ttl_sec=3600,
    )
    pool.quarantine(0, "extra usage balance is empty")
    with pytest.raises(NoSelectableUpstreamKeyError):
        await pool.acquire()
    await pool.release_quarantine(0)
    index = await pool.acquire()
    assert index == 0
    assert pool.status()["keys"][0]["quarantined"] is False
    await pool.release(index)


def test_is_quarantined_reports_current_key_state():
    pool = UpstreamKeyPool(["key-a"], quarantine_ttl_sec=3600)

    assert pool.is_quarantined(0) is False
    pool.quarantine(0, "extra usage balance is empty")
    assert pool.is_quarantined(0) is True

    with pytest.raises(IndexError):
        pool.is_quarantined(1)


@pytest.mark.asyncio
async def test_quarantine_ttl_zero_lasts_until_release():
    from src.infrastructure.gateways.upstream_key_pool import NoSelectableUpstreamKeyError

    pool = UpstreamKeyPool(
        ["key-a"],
        max_concurrent_per_key=0,
        acquire_delay_ms=0,
        quarantine_ttl_sec=0,
    )
    pool.quarantine(0, "extra usage balance is empty")
    assert pool.status()["keys"][0]["quarantined"] is True
    assert pool.status()["keys"][0]["quarantine_remaining_sec"] is None
    with pytest.raises(NoSelectableUpstreamKeyError):
        await pool.acquire()
    await pool.release_quarantine(0)
    index = await pool.acquire()
    assert index == 0
    await pool.release(index)


@pytest.mark.asyncio
async def test_quarantine_expires_after_ttl(monkeypatch):
    pool = UpstreamKeyPool(
        ["key-a"],
        max_concurrent_per_key=0,
        acquire_delay_ms=0,
        quarantine_ttl_sec=10,
    )
    start = 1000.0
    monkeypatch.setattr(
        "src.infrastructure.gateways.upstream_key_pool.time.monotonic",
        lambda: start,
    )
    pool.quarantine(0, "extra usage balance is empty")
    monkeypatch.setattr(
        "src.infrastructure.gateways.upstream_key_pool.time.monotonic",
        lambda: start + 11,
    )
    index = await pool.acquire()
    assert index == 0
    await pool.release(index)
