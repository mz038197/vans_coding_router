import time
from collections import deque
from typing import Callable

_WINDOW_SECONDS = 60.0


class PerMinuteRateLimiter:
    """Allows each name at most `limit` calls in any sliding minute.

    The count lives in this process's memory and resets on restart. The router
    runs one machine, so one process holds every count.
    """

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self._clock = clock
        self._calls: dict[str, deque[float]] = {}

    def allow(self, name: str) -> bool:
        """Count one call for the name, unless the last minute is already full."""
        now = self._clock()
        calls = self._calls.setdefault(name, deque())
        while calls and now - calls[0] >= _WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= self.limit:
            return False
        calls.append(now)
        return True
