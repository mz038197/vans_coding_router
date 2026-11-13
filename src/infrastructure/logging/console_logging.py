"""Print router logs under src to the process output, which is what Fly logs show.

Without a handler of its own, a src log reached the console only through Python's last-resort
output, and that stops as soon as any handler is attached, such as the vans-signals forwarder.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _ConsoleHandler(logging.StreamHandler):
    pass


def start_console_logging() -> logging.Handler:
    """Attach one console handler to the src logger at INFO; a second start replaces the first."""
    src = logging.getLogger("src")
    stop_console_logging()
    handler = _ConsoleHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(_FORMAT))
    src.addHandler(handler)
    if src.level == logging.NOTSET or src.level > logging.INFO:
        src.setLevel(logging.INFO)
    return handler


def stop_console_logging() -> None:
    src = logging.getLogger("src")
    for handler in [h for h in src.handlers if isinstance(h, _ConsoleHandler)]:
        src.removeHandler(handler)
        handler.close()
