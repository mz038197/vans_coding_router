"""`POST /internal/key-check`, called by a Partner Service with its Service Credential (ADR 0076, 0077).

The body is read by hand, not by a Pydantic model: FastAPI's default 422 repeats the
input, and the input is the key.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.application.use_cases.key_check_use_case import KeyCheckUseCase
from src.infrastructure.auth.service_credentials import service_named_by_token

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


def create_key_check_router(
    key_check: KeyCheckUseCase,
    service_tokens: Mapping[str, str],
) -> APIRouter:
    router = APIRouter()

    @router.post("/internal/key-check")
    async def key_check_endpoint(request: Request) -> JSONResponse:
        if _partner_service(request, service_tokens) is None:
            return JSONResponse(UNAUTHORIZED_BODY, status_code=401)
        api_key = await _api_key_from_body(request)
        if api_key is None:
            return JSONResponse(BAD_REQUEST_BODY, status_code=400)
        return JSONResponse(key_check.check(api_key))

    return router
