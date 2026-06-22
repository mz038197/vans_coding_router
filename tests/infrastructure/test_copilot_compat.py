import json

import pytest

from src.infrastructure.gateways.copilot_compat import (
    derive_ollama_native_base,
    normalize_chat_completions_response,
    normalize_chat_completions_sse,
    sanitize_responses_request,
    strip_ollama_cloud_inference_suffix,
    to_ollama_cloud_inference_id,
)


async def _collect_sse(chunks: list[bytes]) -> bytes:
    async def _gen():
        for chunk in chunks:
            yield chunk

    parts: list[bytes] = []
    async for chunk in normalize_chat_completions_sse(_gen()):
        parts.append(chunk)
    return b"".join(parts)


@pytest.mark.asyncio
async def test_normalize_sse_drops_empty_choices_usage_chunk():
    content_chunk = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[{"index":0,"delta":{"role":"assistant","content":"OK"},"finish_reason":null}]}\n\n'
    )
    empty_choices_chunk = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[],"usage":{"total_tokens":12,"prompt_tokens":8,"completion_tokens":4}}\n\n'
    )
    done = b"data: [DONE]\n\n"

    body = await _collect_sse([content_chunk, empty_choices_chunk, done])
    text = body.decode("utf-8")

    assert '"choices":[]' not in text.replace(" ", "")
    assert '"total_tokens":12' in text.replace(" ", "")
    assert '"finish_reason":"stop"' in text.replace(" ", "")
    assert "OK" in text
    assert "data: [DONE]" in text


@pytest.mark.asyncio
async def test_normalize_sse_handles_split_events_across_byte_chunks():
    full = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[],"usage":{"total_tokens":5}}\n\n'
        b"data: [DONE]\n\n"
    )
    split_a = full[:40]
    split_b = full[40:]

    body = await _collect_sse([split_a, split_b])
    assert b"Hi" in body
    assert b'"choices":[]' not in body.replace(b" ", b"")
    assert b'"total_tokens":5' in body.replace(b" ", b"")


@pytest.mark.asyncio
async def test_normalize_sse_prepends_role_when_first_delta_is_reasoning_content():
    reasoning_only = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[{"index":0,"delta":{"reasoning_content":"Thinking"},"finish_reason":null}]}\n\n'
        b"data: [DONE]\n\n"
    )
    body = await _collect_sse([reasoning_only])
    text = body.decode("utf-8")
    assert "assistant" in text
    assert "Thinking" in text
    role_index = text.find("assistant")
    reasoning_index = text.find("Thinking")
    assert role_index != -1
    assert reasoning_index != -1
    assert role_index < reasoning_index


@pytest.mark.asyncio
async def test_normalize_sse_prepends_role_when_first_delta_has_no_role():
    content_only = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[{"index":0,"delta":{"content":"OK"},"finish_reason":null}]}\n\n'
        b"data: [DONE]\n\n"
    )
    body = await _collect_sse([content_only])
    text = body.decode("utf-8")
    assert "assistant" in text
    role_index = text.find("assistant")
    content_index = text.find("OK")
    assert role_index != -1
    assert content_index != -1
    assert role_index < content_index


def test_normalize_nonstream_fills_content_from_reasoning():
    body = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "", "reasoning": "Canberra"},
                "finish_reason": "stop",
            }
        ]
    }
    out = normalize_chat_completions_response(body)
    assert out["choices"][0]["message"]["content"] == "Canberra"


def test_normalize_nonstream_fills_content_from_reasoning_content():
    body = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "", "reasoning_content": "Thinking..."},
                "finish_reason": "stop",
            }
        ]
    }
    out = normalize_chat_completions_response(body)
    assert out["choices"][0]["message"]["content"] == "Thinking..."
    assert out["choices"][0]["message"]["reasoning_content"] == "Thinking..."


def test_normalize_nonstream_prefers_content_over_reasoning_content():
    body = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Answer",
                    "reasoning_content": "Thinking...",
                },
                "finish_reason": "stop",
            }
        ]
    }
    out = normalize_chat_completions_response(body)
    message = out["choices"][0]["message"]
    assert message["content"] == "Answer"
    assert message["reasoning_content"] == "Thinking..."


def test_normalize_nonstream_reasoning_content_before_reasoning():
    body = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Primary",
                    "reasoning": "Secondary",
                },
                "finish_reason": "stop",
            }
        ]
    }
    out = normalize_chat_completions_response(body)
    assert out["choices"][0]["message"]["content"] == "Primary"


def test_sanitize_removes_reasoning_for_non_thinking_model():
    body = {"model": "llama3.2:3b", "input": "hello", "reasoning": {"effort": "high"}}
    out = sanitize_responses_request(body, supports_thinking=False)
    assert "reasoning" not in out


def test_sanitize_keeps_reasoning_for_thinking_model():
    body = {"model": "qwen3-coder-next", "input": "hello", "reasoning": {"effort": "low"}}
    out = sanitize_responses_request(body, supports_thinking=True)
    assert out["reasoning"] == {"effort": "low"}


def test_sanitize_drops_invalid_reasoning_effort():
    body = {"model": "qwen3-coder-next", "input": "hello", "reasoning": {"effort": "turbo"}}
    out = sanitize_responses_request(body, supports_thinking=True)
    assert "reasoning" not in out


@pytest.mark.asyncio
async def test_normalize_sse_converts_inline_error_to_choices():
    error_chunk = (
        b'data: {"error":{"message":"Upstream provider error","type":"server_error"}}\n\n'
        b"data: [DONE]\n\n"
    )
    body = await _collect_sse([error_chunk])
    text = body.decode("utf-8")
    assert "choices" in text
    assert "Upstream provider error" in text
    assert '"error":' not in text.replace(" ", "")


def test_derive_ollama_native_base():
    assert derive_ollama_native_base("https://ollama.com/v1") == "https://ollama.com"
    assert derive_ollama_native_base("https://ollama.com/v1/") == "https://ollama.com"


@pytest.mark.parametrize(
    ("registry", "inference"),
    [
        ("minimax-m3", "minimax-m3:cloud"),
        ("qwen3.5", "qwen3.5:cloud"),
        ("gpt-oss:20b", "gpt-oss:20b-cloud"),
        ("qwen3-coder:480b", "qwen3-coder:480b-cloud"),
        ("user/repo", "user/repo:cloud"),
        ("user/repo:tag", "user/repo:tag-cloud"),
        ("minimax-m3:cloud", "minimax-m3:cloud"),
        ("gpt-oss:20b-cloud", "gpt-oss:20b-cloud"),
    ],
)
def test_to_ollama_cloud_inference_id(registry: str, inference: str):
    assert to_ollama_cloud_inference_id(registry) == inference


@pytest.mark.parametrize(
    ("inference", "registry"),
    [
        ("minimax-m3:cloud", "minimax-m3"),
        ("qwen3.5:cloud", "qwen3.5"),
        ("gpt-oss:20b-cloud", "gpt-oss:20b"),
        ("qwen3-coder:480b-cloud", "qwen3-coder:480b"),
        ("minimax-m3", "minimax-m3"),
    ],
)
def test_strip_ollama_cloud_inference_suffix(inference: str, registry: str):
    assert strip_ollama_cloud_inference_suffix(inference) == registry


@pytest.mark.asyncio
async def test_normalize_sse_emits_role_chunk_when_stream_only_has_done():
    body = await _collect_sse([b"data: [DONE]\n\n"])
    text = body.decode("utf-8")
    assert "choices" in text
    assert "assistant" in text
