from __future__ import annotations

from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse
from starlette.types import Send


class AclosingStreamingResponse(StreamingResponse):
    """StreamingResponse that always aclose()s the body iterator.

    Starlette's default implementation leaves async generators open when the
    client disconnects mid-stream (cancel during send). Cleanup then depends on
    deferred asyncgen finalization, which can leave UpstreamKeyPool slots held.
    """

    async def stream_response(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        iterator: AsyncIterator[bytes | memoryview | str] = self.body_iterator
        try:
            async for chunk in iterator:
                if not isinstance(chunk, (bytes, memoryview)):
                    chunk = chunk.encode(self.charset)
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            aclose = getattr(iterator, "aclose", None)
            if aclose is not None:
                await aclose()
