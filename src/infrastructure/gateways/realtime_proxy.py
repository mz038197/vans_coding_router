from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlencode, urlparse, urlunparse

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


@dataclass(frozen=True)
class RealtimeUpstreamTarget:
    provider_name: str
    upstream_model: str
    ws_url: str
    api_key: str


class UpstreamRealtimeSocket(Protocol):
    async def send(self, message: str | bytes) -> None: ...

    def __aiter__(self) -> Any: ...

    async def close(self) -> None: ...


UpstreamConnect = Callable[[str, dict[str, str]], Awaitable[UpstreamRealtimeSocket]]


def http_base_to_realtime_ws_url(base_url: str, upstream_model: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/realtime"
    query = urlencode({"model": upstream_model})
    return urlunparse((scheme, parsed.netloc, path, "", query, ""))


def rewrite_realtime_client_text(text: str, upstream_model: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(payload, dict):
        return text
    if payload.get("type") != "session.update":
        return text
    session = payload.get("session")
    if not isinstance(session, dict):
        return text
    audio = session.get("audio")
    if isinstance(audio, dict):
        input_audio = audio.get("input")
        if isinstance(input_audio, dict):
            transcription = input_audio.get("transcription")
            if isinstance(transcription, dict) and "model" in transcription:
                transcription = dict(transcription)
                transcription["model"] = upstream_model
                input_audio = dict(input_audio)
                input_audio["transcription"] = transcription
                audio = dict(audio)
                audio["input"] = input_audio
                session = dict(session)
                session["audio"] = audio
                payload = dict(payload)
                payload["session"] = session
                return json.dumps(payload, ensure_ascii=False)
    if "model" in session:
        session = dict(session)
        session["model"] = upstream_model
        payload = dict(payload)
        payload["session"] = session
        return json.dumps(payload, ensure_ascii=False)
    return text


async def proxy_realtime_session(
    client_ws: WebSocket,
    target: RealtimeUpstreamTarget,
    *,
    connect: UpstreamConnect,
) -> str:
    headers = {
        "Authorization": f"Bearer {target.api_key}",
        "OpenAI-Beta": "realtime=v1",
    }
    upstream = await connect(target.ws_url, headers)
    transcript_parts: list[str] = []
    client_task = asyncio.create_task(
        _pump_client_to_upstream(client_ws, upstream, target.upstream_model)
    )
    upstream_task = asyncio.create_task(
        _pump_upstream_to_client(client_ws, upstream, transcript_parts)
    )
    try:
        done, pending = await asyncio.wait(
            {client_task, upstream_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    finally:
        for task in (client_task, upstream_task):
            if not task.done():
                task.cancel()
        await upstream.close()
    return "".join(transcript_parts)


async def _pump_client_to_upstream(
    client_ws: WebSocket,
    upstream: UpstreamRealtimeSocket,
    upstream_model: str,
) -> None:
    try:
        while True:
            message = await client_ws.receive()
            msg_type = message.get("type")
            if msg_type == "websocket.disconnect":
                break
            if "text" in message and message["text"] is not None:
                await upstream.send(rewrite_realtime_client_text(message["text"], upstream_model))
            elif "bytes" in message and message["bytes"] is not None:
                await upstream.send(message["bytes"])
    except WebSocketDisconnect:
        return


async def _pump_upstream_to_client(
    client_ws: WebSocket,
    upstream: UpstreamRealtimeSocket,
    transcript_parts: list[str],
) -> None:
    try:
        async for message in upstream:
            if isinstance(message, (bytes, bytearray)):
                await client_ws.send_bytes(bytes(message))
            else:
                text = str(message)
                _collect_transcript_delta(text, transcript_parts)
                await client_ws.send_text(text)
    except WebSocketDisconnect:
        return


def _collect_transcript_delta(text: str, transcript_parts: list[str]) -> None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    event_type = payload.get("type")
    if event_type in {
        "conversation.item.input_audio_transcription.delta",
        "transcription_session.delta",
        "transcript.text.delta",
    }:
        delta = payload.get("delta")
        if isinstance(delta, str) and delta:
            transcript_parts.append(delta)
        return
    if event_type in {
        "conversation.item.input_audio_transcription.completed",
        "transcript.text.done",
    }:
        transcript = payload.get("transcript") or payload.get("text")
        if isinstance(transcript, str) and transcript:
            transcript_parts.clear()
            transcript_parts.append(transcript)
