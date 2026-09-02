from typing import Any

from contextlib import aclosing

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from src.infrastructure.auth.client_api_key import normalize_api_key
from src.application.dto.chat_dto import ChatCompletionInputDto
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.domain.errors import (
    InvalidModelIdError,
    ServiceUnavailableError,
    SpeechTranscriptionDisabledError,
    SpeechTranscriptionNotSupportedError,
    UpstreamBusyError,
    UpstreamServiceError,
)
from src.presentation.fastapi.auth_responses import openai_auth_error_response
from src.presentation.fastapi.openai_errors import (
    openai_error_response,
    openai_stream_chat_error_bytes,
    openai_stream_error_bytes,
    openai_stream_responses_error_bytes,
)
from src.infrastructure.gateways.realtime_proxy import UpstreamConnect, proxy_realtime_session
from src.infrastructure.routing.token_limit import resolve_chat_output_token_limit
from src.presentation.fastapi.schemas.api import AudioSpeechRequestSchema, ChatCompletionsRequestSchema, ImageGenerationRequestSchema
from src.presentation.fastapi.streaming import AclosingStreamingResponse


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _extract_api_key(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        value = normalize_api_key(auth_header[7:])
        return value or None
    value = normalize_api_key(request.headers.get("X-API-Key"))
    return value or None


def _upstream_error_message(exc: UpstreamServiceError) -> str:
    return exc.user_facing_message()


async def _default_realtime_connect(url: str, headers: dict[str, str]):
    import websockets

    return await websockets.connect(url, additional_headers=headers)


def create_api_router(
    api_use_case: ApiUseCase,
    *,
    auth_use_case: AuthUseCase | None = None,
    realtime_connect: UpstreamConnect | None = None,
) -> APIRouter:
    router = APIRouter(tags=["API"])
    auth = auth_use_case or AuthUseCase(api_key_repo=api_use_case.api_key_repo)
    connect = realtime_connect or _default_realtime_connect

    @router.get("/health")
    async def health():
        return await api_use_case.health()

    @router.get("/v1/models")
    async def list_models():
        return await api_use_case.models()

    @router.get("/v1/auth/check")
    async def auth_check(request: Request):
        api_key = _extract_api_key(request) or ""
        auth_context = getattr(request.state, "auth_context", None)
        if auth_context is not None:
            return {
                "valid": True,
                "key_prefix": auth_context.key_prefix,
                "session_id": auth_context.session_id,
                "class_id": auth_context.class_id,
            }
        return openai_auth_error_response(api_key, api_use_case.api_key_repo)

    async def _stream_with_error_handling(domain_req, api_key, client_ip, auth_context):
        """包含錯誤處理的流式生成器"""
        try:
            async with aclosing(
                api_use_case.chat_stream(domain_req, api_key, client_ip, auth_context)
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_chat_error_bytes(_upstream_error_message(e), model=domain_req.model)
        except UpstreamBusyError as e:
            yield openai_stream_chat_error_bytes(e.message, model=domain_req.model)
        except ServiceUnavailableError as e:
            yield openai_stream_chat_error_bytes(e.message, model=domain_req.model)
        except Exception as e:
            yield openai_stream_chat_error_bytes(str(e), model=domain_req.model)

    async def _responses_stream_with_error_handling(body: dict[str, Any], api_key, client_ip, auth_context):
        model = str(body.get("model") or "")
        try:
            async with aclosing(
                api_use_case.responses_create_stream(body, api_key, client_ip, auth_context)
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_responses_error_bytes(_upstream_error_message(e), model=model)
        except UpstreamBusyError as e:
            yield openai_stream_responses_error_bytes(e.message, model=model)
        except ServiceUnavailableError as e:
            yield openai_stream_responses_error_bytes(e.message, model=model)
        except Exception as e:
            yield openai_stream_responses_error_bytes(str(e), model=model)

    @router.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionsRequestSchema, request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)
        auth_context = getattr(request.state, "auth_context", None)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            return openai_auth_error_response(api_key or "", api_use_case.api_key_repo)

        input_dto = ChatCompletionInputDto(
            model=req.model,
            messages=[m.model_dump() for m in req.messages],
            stream=req.stream,
            temperature=req.temperature,
            max_tokens=resolve_chat_output_token_limit(req.max_tokens, req.max_completion_tokens),
            user=req.user,
            stop=req.stop,
            tools=req.tools,
            tool_choice=req.tool_choice,
        )
        domain_req = input_dto.to_domain()
        api_use_case.validate_model_allowed(domain_req.model, auth_context)

        if domain_req.stream:
            generator = _stream_with_error_handling(domain_req, api_key, client_ip, auth_context)
            return AclosingStreamingResponse(generator, media_type="text/event-stream")

        data = await api_use_case.chat_nonstream(domain_req, api_key, client_ip, auth_context)
        return JSONResponse(content=data)

    @router.post("/v1/responses")
    async def responses_create(request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            return openai_auth_error_response(api_key or "", api_use_case.api_key_repo)

        body: dict[str, Any] = await request.json()
        auth_context = getattr(request.state, "auth_context", None)
        api_use_case.validate_responses_request(body)
        api_use_case.validate_model_allowed(str(body.get("model") or ""), auth_context)

        if body.get("stream"):
            generator = _responses_stream_with_error_handling(body, api_key, client_ip, auth_context)
            return AclosingStreamingResponse(generator, media_type="text/event-stream")

        data = await api_use_case.responses_create(body, api_key, client_ip, auth_context)
        return JSONResponse(content=data)

    async def _images_stream_with_error_handling(body: dict[str, Any], api_key, client_ip, auth_context):
        try:
            async with aclosing(
                api_use_case.images_create_stream(body, api_key, client_ip, auth_context)
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_error_bytes(_upstream_error_message(e), error_type="server_error")
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
            return openai_auth_error_response(api_key or "", api_use_case.api_key_repo)

        body = req.model_dump(exclude_none=True)
        if req.stream:
            generator = _images_stream_with_error_handling(body, api_key, client_ip, auth_context)
            return AclosingStreamingResponse(generator, media_type="text/event-stream")

        data = await api_use_case.images_create(body, api_key, client_ip, auth_context)
        return JSONResponse(content=data)

    @router.get("/v1/images/models")
    async def images_models(request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)
        auth_context = getattr(request.state, "auth_context", None)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            return openai_auth_error_response(api_key or "", api_use_case.api_key_repo)

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
            async with aclosing(
                api_use_case.audio_speech_stream(body, api_key, client_ip, auth_context)
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_error_bytes(_upstream_error_message(e), error_type="server_error")
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
            return openai_auth_error_response(api_key or "", api_use_case.api_key_repo)

        body = req.model_dump(exclude_none=True)
        api_use_case.validate_audio_speech_request(body, auth_context)
        generator = _audio_speech_stream_with_error_handling(body, api_key, client_ip, auth_context)
        media_type = _audio_speech_media_type(body.get("response_format"))
        return AclosingStreamingResponse(generator, media_type=media_type)

    async def _audio_transcriptions_stream_with_error_handling(
        fields: dict[str, Any],
        file: tuple[str, bytes, str | None],
        api_key,
        client_ip,
        auth_context,
    ):
        try:
            async with aclosing(
                api_use_case.audio_transcriptions_create_stream(
                    fields, file, api_key, client_ip, auth_context
                )
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except UpstreamServiceError as e:
            yield openai_stream_error_bytes(_upstream_error_message(e), error_type="server_error")
        except ServiceUnavailableError as e:
            yield openai_stream_error_bytes(e.message, error_type="server_error")
        except Exception as e:
            yield openai_stream_error_bytes(str(e), error_type="server_error")

    @router.post("/v1/audio/transcriptions")
    async def audio_transcriptions_create(request: Request):
        api_key = _extract_api_key(request)
        client_ip = _client_ip(request)
        auth_context = getattr(request.state, "auth_context", None)

        if getattr(request.state, "invalid_api_key", False):
            api_use_case.log_invalid_auth(api_key or "", client_ip)
            return openai_auth_error_response(api_key or "", api_use_case.api_key_repo)

        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return openai_error_response(
                400,
                "Missing file",
                error_type="invalid_request_error",
                code="invalid_request_error",
                param="file",
            )
        file_bytes = await upload.read()
        filename = getattr(upload, "filename", None) or "audio"
        content_type = getattr(upload, "content_type", None)
        fields: dict[str, Any] = {}
        for key, value in form.multi_items():
            if key == "file":
                continue
            if hasattr(value, "read"):
                continue
            fields[key] = value

        api_use_case.validate_audio_transcriptions_request(fields, auth_context)
        file = (str(filename), file_bytes, content_type)
        stream_flag = str(fields.get("stream", "")).lower() in {"1", "true", "yes"}
        if stream_flag:
            generator = _audio_transcriptions_stream_with_error_handling(
                fields, file, api_key, client_ip, auth_context
            )
            return AclosingStreamingResponse(generator, media_type="text/event-stream")

        data = await api_use_case.audio_transcriptions_create(
            fields, file, api_key, client_ip, auth_context
        )
        return JSONResponse(content=data)

    def _extract_ws_api_key(ws: WebSocket) -> str | None:
        auth_header = ws.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            value = normalize_api_key(auth_header[7:])
            return value or None
        value = normalize_api_key(ws.headers.get("x-api-key"))
        if value:
            return value
        query_key = ws.query_params.get("api_key")
        if query_key:
            return normalize_api_key(query_key) or None
        return None

    @router.websocket("/v1/realtime")
    async def realtime_proxy(ws: WebSocket, model: str = Query(default="")):
        api_key = _extract_ws_api_key(ws) or ""
        auth_context = auth.verify_context(api_key)
        if auth_context is None:
            await ws.close(code=1008, reason="invalid_api_key")
            return
        try:
            target = api_use_case.validate_realtime_request(model, auth_context)
        except InvalidModelIdError:
            await ws.close(code=1008, reason="invalid_model_id")
            return
        except SpeechTranscriptionDisabledError:
            await ws.close(code=1008, reason="speech_transcription_disabled")
            return
        except SpeechTranscriptionNotSupportedError:
            await ws.close(code=1008, reason="speech_transcription_not_supported")
            return
        except ServiceUnavailableError:
            await ws.close(code=1013, reason="upstream_unavailable")
            return

        await ws.accept()
        client_ip = ws.client.host if ws.client else None
        transcript_text = ""
        try:
            transcript_text = await proxy_realtime_session(ws, target, connect=connect)
        except WebSocketDisconnect:
            pass
        except Exception:
            try:
                await ws.close(code=1011, reason="realtime_proxy_error")
            except Exception:
                pass
        finally:
            api_use_case.log_realtime_transcription(
                model,
                api_key,
                client_ip,
                auth_context,
                transcript_text,
            )

    return router
