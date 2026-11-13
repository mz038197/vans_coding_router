"""`POST /internal/key-check` and `POST /internal/teacher-classes`, called by a Partner
Service with its Service Credential (ADR 0076, 0077, 0094).

The body is read by hand, not by a Pydantic model: FastAPI's default 422 repeats the
input, and the input is the key.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.application.per_minute_rate_limit import PerMinuteRateLimiter
from src.application.use_cases.key_check_use_case import KeyCheckUseCase
from src.infrastructure.auth.service_credentials import service_named_by_token

logger = logging.getLogger(__name__)

UNAUTHORIZED_BODY = {
    "error": {
        "code": "invalid_service_credential",
        "message": "A Partner Service Service Credential is required.",
    }
}

BAD_REQUEST_BODY = {
    "error": {
        "code": "invalid_key_check_body",
        "message": 'The body must be a JSON object with a string "api_key".',
    }
}

TEACHER_CLASSES_BAD_REQUEST_BODY = {
    "error": {
        "code": "invalid_teacher_classes_body",
        "message": 'The body must be a JSON object with an integer "user_id".',
    }
}

RATE_LIMITED_BODY = {
    "error": {
        "code": "key_check_rate_limited",
        "message": "This Partner Service has made too many Key Check calls this minute.",
    }
}


def _partner_service(request: Request, service_tokens: Mapping[str, str]) -> str | None:
    """The Partner Service the Authorization header names, or None."""
    header = request.headers.get("Authorization", "")
    scheme, _, credential = header.partition(" ")
    if scheme != "Bearer" or not credential.strip():
        return None
    return service_named_by_token(credential.strip(), service_tokens)


async def _api_key_from_body(request: Request) -> str | None:
    """The `api_key` string of the body, or None when the body cannot be read."""
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    api_key = body.get("api_key")
    return api_key if isinstance(api_key, str) else None


async def _user_id_from_body(request: Request) -> int | None:
    """The integer `user_id` of the body, or None when the body cannot be read."""
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    user_id = body.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        return None
    return user_id


def create_key_check_router(
    key_check: KeyCheckUseCase,
    service_tokens: Mapping[str, str],
    rate_limiter: PerMinuteRateLimiter,
) -> APIRouter:
    """`rate_limiter` counts calls per Partner Service; bootstrap builds it from the config."""
    router = APIRouter()

    @router.post("/internal/key-check")
    async def key_check_endpoint(request: Request) -> JSONResponse:
        service = _partner_service(request, service_tokens)
        if service is None:
            return JSONResponse(UNAUTHORIZED_BODY, status_code=401)
        if not rate_limiter.allow(service):
            # Every refused call sends its own ERROR Signal (ADR 0076).
            logger.error(
                "Key Check rate limit: Partner Service %s went over %d calls a minute",
                service,
                rate_limiter.limit,
            )
            return JSONResponse(RATE_LIMITED_BODY, status_code=429)
        api_key = await _api_key_from_body(request)
        if api_key is None:
            return JSONResponse(BAD_REQUEST_BODY, status_code=400)
        return JSONResponse(key_check.check(api_key))

    @router.post("/internal/teacher-classes")
    async def teacher_classes_endpoint(request: Request) -> JSONResponse:
        # Not counted by the Key Check rate limit: it names a user id, not a key to guess.
        if _partner_service(request, service_tokens) is None:
            return JSONResponse(UNAUTHORIZED_BODY, status_code=401)
        user_id = await _user_id_from_body(request)
        if user_id is None:
            return JSONResponse(TEACHER_CLASSES_BAD_REQUEST_BODY, status_code=400)
        return JSONResponse(key_check.teacher_classes(user_id))

    return router
