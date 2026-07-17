from __future__ import annotations

import asyncio
import time

from src.domain.errors import UpstreamBusyError


class UpstreamKeyPool:
    """Least-in-flight key selection with optional per-key concurrency limit."""

    def __init__(
        self,
        keys: list[str],
        *,
        max_concurrent_per_key: int = 0,
        queue_timeout_sec: float = 120.0,
        acquire_delay_ms: int = 0,
    ):
        if not keys:
            raise ValueError("UpstreamKeyPool requires at least one API key")
        self._keys = list(keys)
        self._max_concurrent_per_key = max(0, int(max_concurrent_per_key))
        self._queue_timeout_sec = float(queue_timeout_sec)
        self._acquire_delay_ms = max(0, int(acquire_delay_ms))
        self._in_flight = [0] * len(self._keys)
        self._condition = asyncio.Condition()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def key_at(self, index: int) -> str:
        return self._keys[index]

    def in_flight_snapshot(self) -> list[int]:
        return list(self._in_flight)

    def _pick_index(self) -> int | None:
        best: int | None = None
        best_load = 0
        for index, load in enumerate(self._in_flight):
            if self._max_concurrent_per_key > 0 and load >= self._max_concurrent_per_key:
                continue
            if best is None or load < best_load:
                best = index
                best_load = load
        return best

    async def _release_locked(self, index: int) -> None:
        async with self._condition:
            if 0 <= index < len(self._in_flight) and self._in_flight[index] > 0:
                self._in_flight[index] -= 1
            self._condition.notify(1)

    async def acquire(self) -> int:
        """Acquire a key slot.

        Exception-safe: if cancellation/errors occur after the in-flight counter
        is incremented (including during acquire_delay), the slot is released
        before the exception propagates.
        """
        deadline = time.monotonic() + self._queue_timeout_sec
        acquired: int | None = None
        try:
            async with self._condition:
                while True:
                    index = self._pick_index()
                    if index is not None:
                        self._in_flight[index] += 1
                        acquired = index
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise UpstreamBusyError(
                            "The model provider is busy (queue full). Please wait a moment and try again."
                        )
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                    except TimeoutError as exc:
                        raise UpstreamBusyError(
                            "The model provider is busy (queue timeout). Please wait a moment and try again."
                        ) from exc

            if self._acquire_delay_ms > 0:
                await asyncio.sleep(self._acquire_delay_ms / 1000.0)
            assert acquired is not None
            return acquired
        except BaseException:
            if acquired is not None:
                # Shield so cancellation during delay cannot skip the rollback.
                await asyncio.shield(self._release_locked(acquired))
            raise

    async def release(self, index: int) -> None:
        """Release a previously acquired slot.

        Shielded so cancellation of the caller cannot skip the counter decrement.
        """
        if not (0 <= index < len(self._keys)):
            return
        await asyncio.shield(self._release_locked(index))
