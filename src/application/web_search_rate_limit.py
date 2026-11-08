import time
from typing import Callable

from src.application.per_minute_rate_limit import PerMinuteRateLimiter

WEB_SEARCH_LIMIT_PER_MINUTE = 10


class WebSearchRateLimiter(PerMinuteRateLimiter):
    """A brake on a runaway agent: each API key may search ten times a minute.

    The count serves Web Search only. It is not a usage record and not a quota.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        super().__init__(WEB_SEARCH_LIMIT_PER_MINUTE, clock=clock)
