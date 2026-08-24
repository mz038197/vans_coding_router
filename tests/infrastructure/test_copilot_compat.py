import json

import pytest

from src.infrastructure.gateways.copilot_compat import (
    derive_ollama_native_base,
    normalize_chat_completions_response,
    normalize_chat_completions_sse,
    project_responses_reasoning,
    project_responses_reasoning_sse,
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


async def _collect_responses_sse(chunks: list[bytes]) -> bytes:
    async def _gen():
        for chunk in chunks:
            yield chunk

    parts: list[bytes] = []
    async for chunk in project_responses_reasoning_sse(_gen()):
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
async def test_normalize_sse_prepends_role_when_first_delta_is_reasoning():
    reasoning_only = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[{"index":0,"delta":{"reasoning":"Thinking"},"finish_reason":null}]}\n\n'
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


def test_normalize_nonstream_keeps_reasoning_separate_from_content():
    body = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "", "reasoning": "Thinking trace"},
                "finish_reason": "stop",
            }
        ]
    }
    out = normalize_chat_completions_response(body)
    message = out["choices"][0]["message"]
    assert message["content"] == ""
    assert message["reasoning"] == "Thinking trace"


def test_normalize_nonstream_keeps_reasoning_content_separate_from_content():
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
    message = out["choices"][0]["message"]
    assert message["content"] == ""
    assert message["reasoning_content"] == "Thinking..."


def test_normalize_nonstream_ollama_cloud_shape():
    body = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Four", "reasoning": "2+2=4"},
                "finish_reason": "stop",
            }
        ]
    }
    out = normalize_chat_completions_response(body)
    message = out["choices"][0]["message"]
    assert message["content"] == "Four"
    assert message["reasoning"] == "2+2=4"


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


def test_normalize_nonstream_preserves_both_reasoning_fields_when_content_empty():
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
    message = out["choices"][0]["message"]
    assert message["content"] == ""
    assert message["reasoning_content"] == "Primary"
    assert message["reasoning"] == "Secondary"


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


def test_project_responses_reasoning_fills_summary_and_keeps_content():
    thinking = 'The user asked how many r letters are in "strawberry".'
    body = {
        "id": "resp_1",
        "output": [
            {
                "type": "reasoning",
                "id": "rs_1",
                "status": "completed",
                "summary": [],
                "content": [{"type": "reasoning_text", "text": thinking}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "3"}],
            },
        ],
    }

    out = project_responses_reasoning(body)

    reasoning = out["output"][0]
    assert reasoning["content"] == [{"type": "reasoning_text", "text": thinking}]
    assert reasoning["summary"] == [{"type": "summary_text", "text": thinking}]
    assert out["output"][1]["content"][0]["text"] == "3"
    assert body["output"][0]["summary"] == []


def test_project_responses_reasoning_skips_when_summary_already_present():
    body = {
        "output": [
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [{"type": "summary_text", "text": "already summarized"}],
                "content": [{"type": "reasoning_text", "text": "raw thinking"}],
            }
        ]
    }

    out = project_responses_reasoning(body)

    assert out["output"][0]["summary"] == [{"type": "summary_text", "text": "already summarized"}]
    assert out["output"][0]["content"] == [{"type": "reasoning_text", "text": "raw thinking"}]


def test_project_responses_reasoning_skips_when_no_reasoning_text():
    body = {
        "output": [
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [],
                "content": [],
            }
        ]
    }

    out = project_responses_reasoning(body)
    assert out["output"][0]["summary"] == []


def test_project_responses_reasoning_projects_nested_response_output():
    thinking = "nested thinking"
    body = {
        "type": "response.completed",
        "response": {
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [],
                    "content": [{"type": "reasoning_text", "text": thinking}],
                }
            ]
        },
    }

    out = project_responses_reasoning(body)
    assert out["response"]["output"][0]["summary"] == [{"type": "summary_text", "text": thinking}]
    assert out["response"]["output"][0]["content"][0]["text"] == thinking


@pytest.mark.asyncio
async def test_project_responses_sse_rewrites_reasoning_text_delta():
    event = (
        b'event: response.reasoning_text.delta\n'
        b'data: {"type":"response.reasoning_text.delta","item_id":"rs_1",'
        b'"output_index":0,"content_index":0,"delta":"Thinking"}\n\n'
    )
    text = (await _collect_responses_sse([event])).decode("utf-8")
    compact = text.replace(" ", "")
    assert "event: response.reasoning_summary_text.delta" in text
    assert "response.reasoning_text.delta" not in compact
    assert '"summary_index":0' in compact
    assert '"content_index"' not in compact
    assert "Thinking" in text


@pytest.mark.asyncio
async def test_project_responses_sse_rewrites_reasoning_text_done():
    event = (
        b'event: response.reasoning_text.done\n'
        b'data: {"type":"response.reasoning_text.done","item_id":"rs_1",'
        b'"output_index":0,"content_index":0,"text":"Thinking done"}\n\n'
    )
    text = (await _collect_responses_sse([event])).decode("utf-8")
    compact = text.replace(" ", "")
    assert "event: response.reasoning_summary_text.done" in text
    assert "response.reasoning_text.done" not in compact
    assert '"summary_index":0' in compact
    assert "Thinking done" in text


@pytest.mark.asyncio
async def test_project_responses_sse_rewrites_reasoning_content_part():
    added = (
        b'event: response.content_part.added\n'
        b'data: {"type":"response.content_part.added","item_id":"rs_1","output_index":0,'
        b'"content_index":0,"part":{"type":"reasoning_text","text":""}}\n\n'
    )
    done = (
        b'event: response.content_part.done\n'
        b'data: {"type":"response.content_part.done","item_id":"rs_1","output_index":0,'
        b'"content_index":0,"part":{"type":"reasoning_text","text":"Thinking"}}\n\n'
    )
    text = (await _collect_responses_sse([added, done])).decode("utf-8")
    compact = text.replace(" ", "")
    assert "event: response.reasoning_summary_part.added" in text
    assert "event: response.reasoning_summary_part.done" in text
    assert '"type":"summary_text"' in compact
    assert "response.content_part.added" not in compact
    assert '"content_index"' not in compact


@pytest.mark.asyncio
async def test_project_responses_sse_keeps_output_text_content_part():
    event = (
        b'event: response.content_part.added\n'
        b'data: {"type":"response.content_part.added","item_id":"msg_1","output_index":1,'
        b'"content_index":0,"part":{"type":"output_text","text":""}}\n\n'
    )
    text = (await _collect_responses_sse([event])).decode("utf-8")
    assert "event: response.content_part.added" in text
    assert "output_text" in text


@pytest.mark.asyncio
async def test_project_responses_sse_drops_reasoning_text_when_summary_present():
    added = (
        b'event: response.output_item.added\n'
        b'data: {"type":"response.output_item.added","output_index":0,'
        b'"item":{"id":"rs_1","type":"reasoning","summary":[{"type":"summary_text","text":"shown"}]}}\n\n'
    )
    delta = (
        b'event: response.reasoning_text.delta\n'
        b'data: {"type":"response.reasoning_text.delta","item_id":"rs_1",'
        b'"output_index":0,"content_index":0,"delta":"raw"}\n\n'
    )
    text = (await _collect_responses_sse([added, delta])).decode("utf-8")
    compact = text.replace(" ", "")
    assert "shown" in text
    assert "response.reasoning_text.delta" not in compact
    assert "response.reasoning_summary_text.delta" not in compact


@pytest.mark.asyncio
async def test_project_responses_sse_projects_completed_item():
    event = (
        b'event: response.output_item.done\n'
        b'data: {"type":"response.output_item.done","output_index":0,'
        b'"item":{"id":"rs_1","type":"reasoning","summary":[],'
        b'"content":[{"type":"reasoning_text","text":"raw think"}]}}\n\n'
    )
    text = (await _collect_responses_sse([event])).decode("utf-8")
    payload = json.loads(text.split("data:", 1)[1].strip())
    item = payload["item"]
    assert item["summary"] == [{"type": "summary_text", "text": "raw think"}]
    assert item["content"] == [{"type": "reasoning_text", "text": "raw think"}]


@pytest.mark.asyncio
async def test_project_responses_sse_projects_completed_response():
    event = (
        b"event: response.completed\n"
        b'data: {"type":"response.completed","response":{"output":['
        b'{"type":"reasoning","id":"rs_1","summary":[],'
        b'"content":[{"type":"reasoning_text","text":"done think"}]}]}}\n\n'
    )
    text = (await _collect_responses_sse([event])).decode("utf-8")
    payload = json.loads(text.split("data:", 1)[1].strip())
    item = payload["response"]["output"][0]
    assert item["summary"] == [{"type": "summary_text", "text": "done think"}]
    assert item["content"][0]["text"] == "done think"


@pytest.mark.asyncio
async def test_project_responses_sse_handles_split_events():
    event = (
        b"event: response.reasoning_text.delta\n"
        b'data: {"type":"response.reasoning_text.delta","item_id":"rs_1",'
        b'"output_index":0,"content_index":0,"delta":"Hi"}\n\n'
    )
    text = (await _collect_responses_sse([event[:40], event[40:]])).decode("utf-8")
    assert "event: response.reasoning_summary_text.delta" in text
    assert "Hi" in text


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


@pytest.mark.asyncio
async def test_normalize_sse_converts_string_error_to_choices():
    error_chunk = (
        b'data: {"error":"this model uses extra usage only and your extra usage balance is empty"}\n\n'
        b"data: [DONE]\n\n"
    )
    body = await _collect_sse([error_chunk])
    text = body.decode("utf-8")
    assert "choices" in text
    assert "extra usage balance is empty" in text
    assert '"error":' not in text.replace(" ", "")


def test_encode_responses_stream_error_is_completed_output_text():
    from src.infrastructure.gateways.copilot_compat import encode_responses_stream_error

    text = encode_responses_stream_error("extra usage balance is empty", model="kimi-k3:cloud").decode(
        "utf-8"
    )
    assert "event: response.created" in text
    assert "event: response.completed" in text
    assert "extra usage balance is empty" in text
    assert "output_text" in text
    assert '"type": "error"' not in text
    assert '"type":"error"' not in text.replace(" ", "")


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
