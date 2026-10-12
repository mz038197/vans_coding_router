import time
from collections import deque
from typing import Callable

WEB_SEARCH_LIMIT_PER_MINUTE = 10
_WINDOW_SECONDS = 60.0


class WebSearchRateLimiter:
    """A brake on a runaway agent: each API key may search ten times a minute.

    The count lives in this process's memory and serves Web Search only. It is
    not a usage record and not a quota, and it resets on restart.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._searches: dict[str, deque[float]] = {}

    def allow(self, api_key: str) -> bool:
        """Count one search for the key, unless the last minute is already full."""
        now = self._clock()
        searches = self._searches.setdefault(api_key, deque())
        while searches and now - searches[0] >= _WINDOW_SECONDS:
            searches.popleft()
        if len(searches) >= WEB_SEARCH_LIMIT_PER_MINUTE:
            return False
        searches.append(now)
        return True
