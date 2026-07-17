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
    await pool.release(held)
    assert pool.in_flight_snapshot() == [0]


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
