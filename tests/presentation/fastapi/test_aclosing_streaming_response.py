from __future__ import annotations

import pytest

from src.presentation.fastapi.streaming import AclosingStreamingResponse


@pytest.mark.asyncio
async def test_aclosing_streaming_response_closes_body_iterator_on_incomplete_send():
    closed = False

    async def body():
        nonlocal closed
        try:
            yield b"chunk-1"
            yield b"chunk-2"
        finally:
            closed = True

    response = AclosingStreamingResponse(body(), media_type="text/plain")
    sent: list[dict] = []

    async def send(message):
        sent.append(message)
        if message.get("type") == "http.response.body" and message.get("more_body"):
            raise ConnectionError("client disconnected")

    with pytest.raises(ConnectionError):
        await response.stream_response(send)

    assert closed is True
    assert sent[0]["type"] == "http.response.start"
