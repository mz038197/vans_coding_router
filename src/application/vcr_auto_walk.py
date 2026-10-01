from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable, NoReturn

from src.domain.errors import (
    NoFreeConcurrencySlotError,
    ServiceUnavailableError,
    UpstreamBusyError,
    UpstreamServiceError,
)
from src.domain.extra_usage import is_key_failover_exhaustion
from src.infrastructure.gateways.slot_policy import wait_for_pool_slot
from src.infrastructure.gateways.upstream_key_pool import NoSelectableUpstreamKeyError

Call = Callable[[str], Awaitable[Any]]
OpenStream = Callable[[str], AsyncGenerator[bytes, None]]


@dataclass(frozen=True)
class WalkSuccess:
    model_id: str
    value: Any


class VcrAutoWalk:
    """Try shelf Model IDs from the top, queueing only when every pool is full."""

    def __init__(self, *, public_model: str | None = None, rewrite_sse: bool = False):
        self.public_model = public_model
        self.rewrite_sse = rewrite_sse
        self.model_id: str | None = None

    async def run(self, model_ids: list[str], call: Call) -> WalkSuccess:
        async def once(model_id: str, wait: bool) -> Any:
            token = wait_for_pool_slot.set(wait)
            try:
                return await call(model_id)
            finally:
                wait_for_pool_slot.reset(token)

        model_id, value = await self._finish(model_ids, once)
        self.model_id = model_id
        return WalkSuccess(model_id=model_id, value=value)

    async def stream(self, model_ids: list[str], open_stream: OpenStream) -> AsyncGenerator[bytes, None]:
        skips: list[str] = []
        exhaustion: UpstreamServiceError | None = None
        no_key: BaseException | None = None

        for model_id in model_ids:
            yielded = False
            token = wait_for_pool_slot.set(False)
            try:
                async for chunk in open_stream(model_id):
                    yielded = True
                    yield self._rewrite(chunk)
            except NoFreeConcurrencySlotError:
                if yielded:
                    raise
                skips.append("full")
            except NoSelectableUpstreamKeyError as exc:
                if yielded:
                    raise
                no_key = exc
                skips.append("nokey")
            except UpstreamServiceError as exc:
                if yielded or not is_key_failover_exhaustion(exc.status_code, _upstream_body(exc)):
                    raise
                exhaustion = exc
                skips.append("exhausted")
            else:
                self.model_id = model_id
                return
            finally:
                wait_for_pool_slot.reset(token)

        if _every_skip_was_full(skips, model_ids):
            token = wait_for_pool_slot.set(True)
            try:
                async for chunk in open_stream(model_ids[0]):
                    yield self._rewrite(chunk)
            except UpstreamBusyError as exc:
                raise _busy(exc, self.public_model) from exc
            else:
                self.model_id = model_ids[0]
                return
            finally:
                wait_for_pool_slot.reset(token)

        _raise_terminal(exhaustion, no_key)

    async def _finish(self, model_ids: list[str], once: Callable[[str, bool], Awaitable[Any]]) -> tuple[str, Any]:
        skips: list[str] = []
        exhaustion: UpstreamServiceError | None = None
        no_key: BaseException | None = None
        for model_id in model_ids:
            try:
                return model_id, await once(model_id, False)
            except NoFreeConcurrencySlotError:
                skips.append("full")
            except NoSelectableUpstreamKeyError as exc:
                no_key = exc
                skips.append("nokey")
            except UpstreamServiceError as exc:
                if not is_key_failover_exhaustion(exc.status_code, _upstream_body(exc)):
                    raise
                exhaustion = exc
                skips.append("exhausted")
        if _every_skip_was_full(skips, model_ids):
            try:
                return model_ids[0], await once(model_ids[0], True)
            except UpstreamBusyError as exc:
                raise _busy(exc, self.public_model) from exc
        _raise_terminal(exhaustion, no_key)

    def _rewrite(self, chunk: bytes) -> bytes:
        if not self.rewrite_sse or not self.public_model:
            return chunk
        return rewrite_sse_model(chunk, self.public_model)


def stamp_reply_model(body: Any, model: str) -> Any:
    if not isinstance(body, dict):
        return body
    stamped = dict(body)
    stamped["model"] = model
    return stamped


def rewrite_sse_model(chunk: bytes, model: str) -> bytes:
    if b"data:" not in chunk:
        return chunk
    trailing = chunk.endswith(b"\n\n")
    parts = [part for part in chunk.split(b"\n\n") if part]
    rewritten = [_rewrite_sse_event(part, model) for part in parts]
    joined = b"\n\n".join(rewritten)
    if trailing:
        return joined + b"\n\n"
    return joined


def _rewrite_sse_event(event: bytes, model: str) -> bytes:
    lines = event.split(b"\n")
    rewritten: list[bytes] = []
    for line in lines:
        if not line.startswith(b"data:"):
            rewritten.append(line)
            continue
        raw = line[5:].strip()
        if raw == b"[DONE]":
            rewritten.append(line)
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            rewritten.append(line)
            continue
        if isinstance(payload, dict):
            _stamp_payload_model(payload, model)
            rewritten.append(b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            continue
        rewritten.append(line)
    return b"\n".join(rewritten)


def _stamp_payload_model(payload: dict[str, Any], model: str) -> None:
    if isinstance(payload.get("model"), str):
        payload["model"] = model
    response = payload.get("response")
    if isinstance(response, dict) and isinstance(response.get("model"), str):
        response["model"] = model


def _upstream_body(exc: UpstreamServiceError) -> Any:
    details = exc.details or {}
    return details.get("body")


def _every_skip_was_full(skips: list[str], model_ids: list[str]) -> bool:
    return bool(model_ids) and len(skips) == len(model_ids) and all(kind == "full" for kind in skips)


def _busy(exc: UpstreamBusyError, public_model: str | None) -> UpstreamBusyError:
    if not public_model:
        return exc
    return UpstreamBusyError(exc.message, public_model=public_model)


def _raise_terminal(exhaustion: UpstreamServiceError | None, no_key: BaseException | None) -> NoReturn:
    if exhaustion is not None:
        raise exhaustion
    if no_key is not None:
        raise ServiceUnavailableError("此 provider 沒有可選的上游金鑰") from no_key
    raise ServiceUnavailableError("此呼叫沒有可用的 Model ID")
