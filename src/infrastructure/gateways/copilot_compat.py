from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

import httpx

VALID_REASONING_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})
_THINKING_CACHE_TTL_SECONDS = 900.0


def is_ollama_provider(provider_name: str, base_url: str) -> bool:
    if provider_name == "ollama_cloud":
        return True
    host = urlparse(base_url).netloc.lower()
    return host in {"ollama.com", "www.ollama.com"}


def derive_ollama_native_base(openai_base_url: str) -> str | None:
    parsed = urlparse(openai_base_url.rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def sanitize_responses_request(body: dict[str, Any], supports_thinking: bool) -> dict[str, Any]:
    """Strip reasoning when the upstream model cannot think."""
    out = deepcopy(body)

    reasoning = out.get("reasoning")
    if not isinstance(reasoning, dict):
        if not supports_thinking:
            out.pop("reasoning", None)
        return out

    if not supports_thinking:
        out.pop("reasoning", None)
        return out

    effort = reasoning.get("effort")
    if effort is not None and effort not in VALID_REASONING_EFFORTS:
        out.pop("reasoning", None)

    return out


def _assistant_visible_text(message: dict[str, Any]) -> str:
    raw = message.get("content")
    if raw is None:
        text = ""
    elif isinstance(raw, str):
        text = raw
    else:
        text = str(raw)
    if text.strip():
        return text
    for key in ("thinking", "reasoning"):
        alt = message.get(key)
        if isinstance(alt, str) and alt.strip():
            return alt
    return text


def normalize_chat_completions_response(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return body

    out = dict(body)
    normalized_choices: list[Any] = []
    for choice in choices:
        if not isinstance(choice, dict):
            normalized_choices.append(choice)
            continue
        choice_out = dict(choice)
        message = choice_out.get("message")
        if isinstance(message, dict):
            message_out = dict(message)
            if message_out.get("tool_calls"):
                raw = message_out.get("content")
                if raw is None:
                    message_out["content"] = ""
            else:
                message_out["content"] = _assistant_visible_text(message_out)
            choice_out["message"] = message_out
        normalized_choices.append(choice_out)
    out["choices"] = normalized_choices
    return out


def _is_empty_choices_chunk(payload: dict[str, Any]) -> bool:
    if payload.get("object") != "chat.completion.chunk":
        return False
    choices = payload.get("choices")
    return isinstance(choices, list) and len(choices) == 0


def _chunk_has_meaningful_delta(payload: dict[str, Any]) -> bool:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return False
    if delta.get("role"):
        return True
    content = delta.get("content")
    if isinstance(content, str) and content:
        return True
    if delta.get("tool_calls"):
        return True
    return False


def _make_assistant_role_chunk(payload: dict[str, Any]) -> bytes:
    chunk = {
        "id": payload.get("id", "chatcmpl-router"),
        "object": "chat.completion.chunk",
        "created": payload.get("created", int(time.time())),
        "model": payload.get("model", ""),
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")


def _encode_sse_data(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


async def normalize_chat_completions_sse(chunks: AsyncGenerator[bytes, None]) -> AsyncGenerator[bytes, None]:
    buffer = b""
    saw_meaningful_choice = False
    pending_role_chunk: bytes | None = None
    first_payload: dict[str, Any] | None = None

    async for chunk in chunks:
        buffer += chunk
        while b"\n\n" in buffer:
            event, buffer = buffer.split(b"\n\n", 1)
            if not event.strip():
                continue

            data_lines = [line[5:].strip() for line in event.split(b"\n") if line.startswith(b"data:")]
            if not data_lines:
                yield event + b"\n\n"
                continue

            raw_data = b"\n".join(data_lines).decode("utf-8", errors="replace").strip()
            if raw_data == "[DONE]":
                if pending_role_chunk is not None:
                    yield pending_role_chunk
                    pending_role_chunk = None
                yield b"data: [DONE]\n\n"
                continue

            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                yield event + b"\n\n"
                continue

            if not isinstance(payload, dict):
                yield event + b"\n\n"
                continue

            if _is_empty_choices_chunk(payload):
                continue

            if first_payload is None:
                first_payload = payload

            if _chunk_has_meaningful_delta(payload):
                delta = payload["choices"][0]["delta"]
                if not saw_meaningful_choice and not delta.get("role"):
                    pending_role_chunk = _make_assistant_role_chunk(first_payload or payload)
                saw_meaningful_choice = True
                if pending_role_chunk is not None:
                    yield pending_role_chunk
                    pending_role_chunk = None

            yield _encode_sse_data(payload)

    if buffer.strip():
        yield buffer


class OllamaThinkingCache:
    def __init__(self, ttl_seconds: float = _THINKING_CACHE_TTL_SECONDS):
        self._ttl_seconds = ttl_seconds
        self._cache: dict[tuple[str, str], tuple[bool, float]] = {}

    async def supports_thinking(
        self,
        client: httpx.AsyncClient,
        native_base: str,
        model: str,
        headers: dict[str, str],
    ) -> bool:
        cache_key = (native_base, model)
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and cached[1] > now:
            return cached[0]

        supports = False
        try:
            response = await client.post(
                f"{native_base.rstrip('/')}/api/show",
                headers=headers,
                json={"model": model},
            )
            if response.status_code == 200:
                data = response.json()
                capabilities = data.get("capabilities")
                if isinstance(capabilities, list):
                    supports = "thinking" in capabilities
        except Exception:
            supports = False

        self._cache[cache_key] = (supports, now + self._ttl_seconds)
        return supports
