"""A brake on a runaway agent: each API key may search ten times a minute.

The count serves Web Search only. It is not a usage record and not a quota. The
limiter is a plain `PerMinuteRateLimiter(WEB_SEARCH_LIMIT_PER_MINUTE)`.
"""

WEB_SEARCH_LIMIT_PER_MINUTE = 10
