from __future__ import annotations

import asyncio
import time
from typing import Any

from src.domain.errors import UpstreamBusyError


class NoSelectableUpstreamKeyError(Exception):
    """No key is selectable: all quarantined and/or excluded from this acquire."""


class UpstreamKeyPool:
    """Least-in-flight key selection with optional per-key concurrency limit."""

    def __init__(
        self,
        keys: list[str],
        *,
        max_concurrent_per_key: int = 0,
        queue_timeout_sec: float = 120.0,
        acquire_delay_ms: int = 0,
        quarantine_ttl_sec: float = 3600.0,
    ):
        if not keys:
            raise ValueError("UpstreamKeyPool requires at least one API key")
        self._keys = list(keys)
        self._max_concurrent_per_key = max(0, int(max_concurrent_per_key))
        self._queue_timeout_sec = float(queue_timeout_sec)
        self._acquire_delay_ms = max(0, int(acquire_delay_ms))
        self._quarantine_ttl_sec = max(0.0, float(quarantine_ttl_sec))
        self._in_flight = [0] * len(self._keys)
        self._quarantined_until: list[float | None] = [None] * len(self._keys)
        self._last_extra_usage_message: str | None = None
        self._waiting = 0
        self._busy_total = 0
        self._condition = asyncio.Condition()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    @property
    def max_concurrent_per_key(self) -> int:
        return self._max_concurrent_per_key

    @property
    def last_extra_usage_message(self) -> str | None:
        return self._last_extra_usage_message

    def key_at(self, index: int) -> str:
        return self._keys[index]

    def in_flight_snapshot(self) -> list[int]:
        return list(self._in_flight)

    def all_quarantined(self) -> bool:
        now = time.monotonic()
        return all(self._is_quarantined(i, now) for i in range(len(self._keys)))

    def is_quarantined(self, index: int) -> bool:
        if not (0 <= index < len(self._keys)):
            raise IndexError(f"key index {index} out of range")
        return self._is_quarantined(index, time.monotonic())

    def quarantine(self, index: int, message: str | None = None) -> None:
        if not (0 <= index < len(self._keys)):
            return
        if message and message.strip():
            self._last_extra_usage_message = message.strip()
        # TTL <= 0 means quarantine until Quarantine Release (no auto-expiry).
        if self._quarantine_ttl_sec <= 0:
            self._quarantined_until[index] = float("inf")
            return
        self._quarantined_until[index] = time.monotonic() + self._quarantine_ttl_sec

    async def release_quarantine(self, index: int) -> None:
        """End Key Quarantine for a key and wake acquire waiters."""
        if not (0 <= index < len(self._keys)):
            return
        async with self._condition:
            self._quarantined_until[index] = None
            self._condition.notify_all()

    def status(self) -> dict[str, Any]:
        """Sanitized pool snapshot (no API key material)."""
        cap = self._max_concurrent_per_key if self._max_concurrent_per_key > 0 else None
        in_flight = list(self._in_flight)
        capacity = (cap * len(self._keys)) if cap is not None else None
        now = time.monotonic()
        keys: list[dict[str, Any]] = []
        for i, load in enumerate(in_flight):
            quarantined = self._is_quarantined(i, now)
            remaining = self._quarantine_remaining_sec(i, now) if quarantined else None
            keys.append(
                {
                    "index": i,
                    "in_flight": load,
                    "cap": cap,
                    "quarantined": quarantined,
                    "quarantine_remaining_sec": remaining,
                }
            )
        return {
            "key_count": len(self._keys),
            "max_concurrent_per_key": self._max_concurrent_per_key,
            "capacity": capacity,
            "in_flight_total": sum(in_flight),
            "waiting": self._waiting,
            "busy_total": self._busy_total,
            "keys": keys,
        }

    def _is_quarantined(self, index: int, now: float) -> bool:
        until = self._quarantined_until[index]
        if until is None:
            return False
        if now >= until:
            self._quarantined_until[index] = None
            return False
        return True

    def _quarantine_remaining_sec(self, index: int, now: float) -> float | None:
        until = self._quarantined_until[index]
        if until is None:
            return None
        if until == float("inf"):
            return None  # quarantined with no auto-expiry; UI shows "隔離中"
        remaining = until - now
        if remaining <= 0:
            self._quarantined_until[index] = None
            return None
        return round(remaining, 1)

    def _has_candidate_keys(self, exclude: frozenset[int], now: float) -> bool:
        for index in range(len(self._keys)):
            if index in exclude:
                continue
            if self._is_quarantined(index, now):
                continue
            return True
        return False

    def _pick_index(self, exclude: frozenset[int], now: float) -> int | None:
        best: int | None = None
        best_load = 0
        for index, load in enumerate(self._in_flight):
            if index in exclude:
                continue
            if self._is_quarantined(index, now):
                continue
            if self._max_concurrent_per_key > 0 and load >= self._max_concurrent_per_key:
                continue
            if best is None or load < best_load:
                best = index
                best_load = load
        return best

    def _raise_busy(self, message: str, *, cause: BaseException | None = None) -> None:
        self._busy_total += 1
        if cause is not None:
            raise UpstreamBusyError(message) from cause
        raise UpstreamBusyError(message)

    async def _release_locked(self, index: int) -> None:
        async with self._condition:
            if 0 <= index < len(self._in_flight) and self._in_flight[index] > 0:
                self._in_flight[index] -= 1
            self._condition.notify(1)

    async def acquire(self, exclude: frozenset[int] | None = None) -> int:
        """Acquire a key slot.

        Exception-safe: if cancellation/errors occur after the in-flight counter
        is incremented (including during acquire_delay), the slot is released
        before the exception propagates.
        """
        excluded = exclude if exclude is not None else frozenset()
        deadline = time.monotonic() + self._queue_timeout_sec
        acquired: int | None = None
        waiting = False
        try:
            async with self._condition:
                while True:
                    now = time.monotonic()
                    if not self._has_candidate_keys(excluded, now):
                        raise NoSelectableUpstreamKeyError()
                    index = self._pick_index(excluded, now)
                    if index is not None:
                        if waiting:
                            self._waiting -= 1
                            waiting = False
                        self._in_flight[index] += 1
                        acquired = index
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._raise_busy(
                            "The model provider is busy (queue full). Please wait a moment and try again."
                        )
                    if not waiting:
                        self._waiting += 1
                        waiting = True
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                    except TimeoutError as exc:
                        self._raise_busy(
                            "The model provider is busy (queue timeout). Please wait a moment and try again.",
                            cause=exc,
                        )

            if self._acquire_delay_ms > 0:
                await asyncio.sleep(self._acquire_delay_ms / 1000.0)
            assert acquired is not None
            return acquired
        except BaseException:
            if waiting:
                async with self._condition:
                    if self._waiting > 0:
                        self._waiting -= 1
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
