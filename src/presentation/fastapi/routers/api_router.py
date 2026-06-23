from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.application.dto.chat_dto import ChatCompletionInputDto
from src.application.use_cases.api_use_case import ApiUseCase
from src.domain.errors import AuthenticationError, ServiceUnavailableError, UpstreamServiceError
from src.presentation.fastapi.openai_errors import (
    openai_error_response,
    openai_stream_chat_error_bytes,
    openai_stream_error_bytes,
)
from src.presentation.fastapi.schemas.api import AudioSpeechRequestSchema, ChatCompletionsRequestSchema, ImageGenerationRequestSchema


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _extract_api_key(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.headers.get("X-API-Key")


def create_api_router(api_use_case: ApiUseCase) -> APIRouter:
    router = APIRouter(tags=["API"])

    @router.get("/health")
    async def health():
        return await api_use_case.health()

    @router.get("/v1/models")
    async def list_models():
        return await api_use_case.models()

    async def _stream_with_error_handling(domain_req, api_key, client_ip, auth_context):
        """包含錯誤處理的流式生成器"""
        try:
            async for chunk in api_use_case.chat_stream(domain_req, api_key, client_ip, auth_context):
                yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_chat_error_bytes(e.message, model=domain_req.model)
        except ServiceUnavailableError as e:
            yield openai_stream_chat_error_bytes(e.message, model=domain_req.model)
        except Exception as e:
            yield openai_stream_chat_error_bytes(str(e), model=domain_req.model)

    async def _responses_stream_with_error_handling(body: dict[str, Any], api_key, client_ip, auth_context):
        try:
            async for chunk in api_use_case.responses_create_stream(body, api_key, client_ip, auth_context):
                yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_error_bytes(e.message, error_type="server_error")
        except ServiceUnavailableError as e:
            yield openai_stream_error_bytes(e.message, error_type="server_error")
        except Exception as e:
            yield openai_stream_error_bytes(str(e), error_type="server_error")

    @router.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionsRequestSchema, request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)
        auth_context = getattr(request.state, "auth_context", None)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            err = AuthenticationError()
            return openai_error_response(
                err.status_code,
                err.message,
                error_type="invalid_request_error",
                code="invalid_api_key",
            )

        input_dto = ChatCompletionInputDto(
            model=req.model,
            messages=[m.model_dump() for m in req.messages],
            stream=req.stream,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            user=req.user,
            stop=req.stop,
            tools=req.tools,
            tool_choice=req.tool_choice,
        )
        domain_req = input_dto.to_domain()

        if domain_req.stream:
            generator = _stream_with_error_handling(domain_req, api_key, client_ip, auth_context)
            return StreamingResponse(generator, media_type="text/event-stream")

        data = await api_use_case.chat_nonstream(domain_req, api_key, client_ip, auth_context)
        return JSONResponse(content=data)

    @router.post("/v1/responses")
    async def responses_create(request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            err = AuthenticationError()
            return openai_error_response(
                err.status_code,
                err.message,
                error_type="invalid_request_error",
                code="invalid_api_key",
            )

        body: dict[str, Any] = await request.json()
        auth_context = getattr(request.state, "auth_context", None)
        api_use_case.validate_responses_request(body)

        if body.get("stream"):
            generator = _responses_stream_with_error_handling(body, api_key, client_ip, auth_context)
            return StreamingResponse(generator, media_type="text/event-stream")

        data = await api_use_case.responses_create(body, api_key, client_ip, auth_context)
        return JSONResponse(content=data)

    async def _images_stream_with_error_handling(body: dict[str, Any], api_key, client_ip, auth_context):
        try:
            async for chunk in api_use_case.images_create_stream(body, api_key, client_ip, auth_context):
                yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_error_bytes(e.message, error_type="server_error")
        except ServiceUnavailableError as e:
            yield openai_stream_error_bytes(e.message, error_type="server_error")
        except Exception as e:
            yield openai_stream_error_bytes(str(e), error_type="server_error")

    @router.post("/v1/images")
    async def images_create(req: ImageGenerationRequestSchema, request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)
        auth_context = getattr(request.state, "auth_context", None)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            err = AuthenticationError()
            return openai_error_response(
                err.status_code,
                err.message,
                error_type="invalid_request_error",
                code="invalid_api_key",
            )

        body = req.model_dump(exclude_none=True)
        if req.stream:
            generator = _images_stream_with_error_handling(body, api_key, client_ip, auth_context)
            return StreamingResponse(generator, media_type="text/event-stream")

        data = await api_use_case.images_create(body, api_key, client_ip, auth_context)
        return JSONResponse(content=data)

    @router.get("/v1/images/models")
    async def images_models(request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)
        auth_context = getattr(request.state, "auth_context", None)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            err = AuthenticationError()
            return openai_error_response(
                err.status_code,
                err.message,
                error_type="invalid_request_error",
                code="invalid_api_key",
            )

        data = await api_use_case.images_models(api_key, client_ip, auth_context)
        return JSONResponse(content=data)

    def _audio_speech_media_type(response_format: str | None) -> str:
        if response_format == "pcm":
            return "audio/pcm"
        if response_format == "wav":
            return "audio/wav"
        if response_format == "mp3":
            return "audio/mpeg"
        if response_format == "opus":
            return "audio/opus"
        if response_format == "aac":
            return "audio/aac"
        if response_format == "flac":
            return "audio/flac"
        return "application/octet-stream"

    async def _audio_speech_stream_with_error_handling(body: dict[str, Any], api_key, client_ip, auth_context):
        try:
            async for chunk in api_use_case.audio_speech_stream(body, api_key, client_ip, auth_context):
                yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_error_bytes(e.message, error_type="server_error")
        except ServiceUnavailableError as e:
            yield openai_stream_error_bytes(e.message, error_type="server_error")
        except Exception as e:
            yield openai_stream_error_bytes(str(e), error_type="server_error")

    @router.post("/v1/audio/speech")
    async def audio_speech_create(req: AudioSpeechRequestSchema, request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)
        auth_context = getattr(request.state, "auth_context", None)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            err = AuthenticationError()
            return openai_error_response(
                err.status_code,
                err.message,
                error_type="invalid_request_error",
                code="invalid_api_key",
            )

        body = req.model_dump(exclude_none=True)
        api_use_case.validate_audio_speech_request(body, auth_context)
        generator = _audio_speech_stream_with_error_handling(body, api_key, client_ip, auth_context)
        media_type = _audio_speech_media_type(body.get("response_format"))
        return StreamingResponse(generator, media_type=media_type)

    return router
