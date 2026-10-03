"""Post each ERROR log under src to vans-signals. The caller does not wait."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

import httpx

SIGNAL_SOURCE = "vans-coding-router"
SIGNAL_TIMEOUT_SEC = 2.0
_FAILURE_LOGGER = "vans_signals_forwarder"


class SignalForwarder(logging.Handler):
    def __init__(self, url: str, token: str):
        super().__init__(level=logging.ERROR)
        self._url = url.rstrip("/") + "/signals"
        self._token = token

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        payload = {
            "log_time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "logger_name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "source": SIGNAL_SOURCE,
        }
        threading.Thread(target=self._post, args=(payload,), daemon=True).start()

    def _post(self, payload: dict) -> None:
        try:
            response = httpx.post(
                self._url,
                json=payload,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=SIGNAL_TIMEOUT_SEC,
            )
            response.raise_for_status()
        except Exception as exc:
            logging.getLogger(_FAILURE_LOGGER).error(
                "Signal post failed: %s",
                type(exc).__name__,
            )

    def close(self) -> None:
        logging.getLogger("src").removeHandler(self)
        super().close()


def start_signal_forwarding(
    url: str | None = None,
    token: str | None = None,
) -> SignalForwarder | None:
    destination = (url if url is not None else os.getenv("VANS_SIGNALS_URL") or "").strip()
    bearer = (token if token is not None else os.getenv("VANS_SIGNALS_TOKEN") or "").strip()
    if not destination or not bearer:
        return None
    forwarder = SignalForwarder(destination, bearer)
    logging.getLogger("src").addHandler(forwarder)
    return forwarder
