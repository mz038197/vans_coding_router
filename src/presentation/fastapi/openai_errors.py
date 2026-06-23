import json
from typing import Any

from fastapi.responses import JSONResponse

from src.infrastructure.gateways.copilot_compat import encode_chat_stream_error

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
RESPONSES_PATH = "/v1/responses"
IMAGES_PATH = "/v1/images"
IMAGES_MODELS_PATH = "/v1/images/models"
AUDIO_SPEECH_PATH = "/v1/audio/speech"
OPENAI_COMPAT_PATHS = frozenset({
    CHAT_COMPLETIONS_PATH,
    RESPONSES_PATH,
    IMAGES_PATH,
    IMAGES_MODELS_PATH,
    AUDIO_SPEECH_PATH,
})


def is_chat_completions_path(path: str) -> bool:
    return path == CHAT_COMPLETIONS_PATH


def is_responses_path(path: str) -> bool:
    return path == RESPONSES_PATH


def is_openai_compatible_path(path: str) -> bool:
    return path in OPENAI_COMPAT_PATHS


def make_openai_error_body(
    message: str,
    *,
    error_type: str = "api_error",
    code: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }


def openai_error_response(
    status_code: int,
    message: str,
    *,
    error_type: str = "api_error",
    code: str | None = None,
    param: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=make_openai_error_body(
            message,
            error_type=error_type,
            code=code,
            param=param,
        ),
    )


def openai_stream_error_bytes(
    message: str,
    *,
    error_type: str = "server_error",
    code: str | None = None,
    param: str | None = None,
) -> bytes:
    payload = make_openai_error_body(
        message,
        error_type=error_type,
        code=code,
        param=param,
    )
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def openai_stream_chat_error_bytes(message: str, *, model: str = "") -> bytes:
    return encode_chat_stream_error(message, model=model)
