"""Service Credentials of Partner Services (ADR 0076).

`VCR_SERVICE_TOKENS` is a JSON object mapping the SHA-256 hex of each credential to
the Partner Service it names, the same shape and rules as vans-signals'
`SIGNALS_TOKENS` (`load_signals_tokens` / `service_named_by_token`). One Partner
Service may be named by two hashes during a rotation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping

SERVICE_TOKENS_ENV = "VCR_SERVICE_TOKENS"

_TOKEN_HASH = re.compile(r"[0-9a-f]{64}")


def load_service_tokens(raw: str | None) -> dict[str, str]:
    """Parse `VCR_SERVICE_TOKENS`. A malformed value raises ValueError."""
    if raw is None or raw.strip() == "":
        raise ValueError(f"{SERVICE_TOKENS_ENV} is missing")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{SERVICE_TOKENS_ENV} is not valid JSON") from exc
    if not isinstance(parsed, dict) or len(parsed) == 0:
        raise ValueError(f"{SERVICE_TOKENS_ENV} must be a non-empty JSON object")
    tokens: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or _TOKEN_HASH.fullmatch(key) is None:
            raise ValueError(f"{SERVICE_TOKENS_ENV} keys must be 64 lowercase hex")
        if not isinstance(value, str) or value == "":
            raise ValueError(f"{SERVICE_TOKENS_ENV} values must be non-empty strings")
        tokens[key] = value
    return tokens


def service_tokens_from_environment(raw: str | None, *, production: bool) -> dict[str, str]:
    """The map the router serves with.

    Unset outside production gives an empty map, so local development starts and every
    Key Check call gets 401. Unset in production, or set but malformed anywhere, refuses
    to start.
    """
    if (raw is None or raw.strip() == "") and not production:
        return {}
    return load_service_tokens(raw)


def service_named_by_token(presented: str, tokens: Mapping[str, str]) -> str | None:
    """The Partner Service a presented credential names, compared in constant time."""
    presented_digest = hashlib.sha256(presented.encode("utf-8")).digest()
    named = None
    for stored_hex, service in tokens.items():
        if hmac.compare_digest(presented_digest, bytes.fromhex(stored_hex)):
            named = service
    return named
