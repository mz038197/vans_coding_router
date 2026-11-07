from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.entities.chat import ChatCompletionRequest, ChatMessage
from src.infrastructure.config import ProviderSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway


@pytest.fixture
def ollama_gateway():
    provider = ProviderSettings(
        name="ollama_cloud",
        type="openai_compatible",
        base_url="https://ollama.com/v1",
        api_key_env="OLLAMA_CLOUD_API_KEY",
    )
    gateway = OpenAICompatibleGateway(provider, timeout=30.0)
    mock_client = AsyncMock()
    gateway._client = mock_client
    return gateway, mock_client


@pytest.mark.asyncio
async def test_responses_create_strips_reasoning_when_model_not_thinking(ollama_gateway):
    gateway, mock_client = ollama_gateway

    show_response = MagicMock()
    show_response.status_code = 200
    show_response.json.return_value = {"capabilities": ["completion"]}

    responses_response = MagicMock()
    responses_response.status_code = 200
    responses_response.json.return_value = {"id": "resp_1", "object": "response", "output": []}

    mock_client.post = AsyncMock(return_value=show_response)
    mock_client.request = AsyncMock(return_value=responses_response)

    with patch.dict("os.environ", {"OLLAMA_CLOUD_API_KEY": "test-key"}):
        result = await gateway.responses_create(
            {
                "model": "llama3.2:3b",
                "input": "hello",
                "reasoning": {"effort": "high"},
            }
        )

    assert result["id"] == "resp_1"
    forwarded = mock_client.request.call_args.kwargs["json"]
    assert "reasoning" not in forwarded


@pytest.mark.asyncio
async def test_responses_create_keeps_reasoning_for_thinking_model(ollama_gateway):
    gateway, mock_client = ollama_gateway

    show_response = MagicMock()
    show_response.status_code = 200
    show_response.json.return_value = {"capabilities": ["completion", "thinking"]}

    responses_response = MagicMock()
    responses_response.status_code = 200
    responses_response.json.return_value = {"id": "resp_2", "object": "response", "output": []}

    mock_client.post = AsyncMock(return_value=show_response)
    mock_client.request = AsyncMock(return_value=responses_response)

    with patch.dict("os.environ", {"OLLAMA_CLOUD_API_KEY": "test-key"}):
        await gateway.responses_create(
            {
                "model": "qwen3-coder-next",
                "input": "hello",
                "reasoning": {"effort": "low"},
            }
        )

    forwarded = mock_client.request.call_args.kwargs["json"]
    assert forwarded["reasoning"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_chat_stream_filters_empty_choices_from_upstream(ollama_gateway):
    gateway, mock_client = ollama_gateway

    content_chunk = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[{"index":0,"delta":{"role":"assistant","content":"OK"},"finish_reason":null}]}\n\n'
    )
    empty_choices_chunk = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"m",'
        b'"choices":[],"usage":{"total_tokens":12}}\n\n'
    )
    done = b"data: [DONE]\n\n"

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_bytes(self):
            for chunk in (content_chunk, empty_choices_chunk, done):
                yield chunk

    mock_client.stream = MagicMock(return_value=FakeStream())

    with patch.dict("os.environ", {"OLLAMA_CLOUD_API_KEY": "test-key"}):
        req = ChatCompletionRequest(
            model="m",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )
        parts: list[bytes] = []
        async for chunk in gateway.chat_completions_stream(req):
            parts.append(chunk)

    body = b"".join(parts).decode("utf-8")
    assert '"choices":[]' not in body.replace(" ", "")
    assert '"total_tokens":12' in body.replace(" ", "")
    assert "OK" in body


@pytest.mark.asyncio
async def test_chat_completions_omits_max_tokens_when_unset(ollama_gateway):
    gateway, mock_client = ollama_gateway

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
    }
    mock_client.request = AsyncMock(return_value=response)

    with patch.dict("os.environ", {"OLLAMA_CLOUD_API_KEY": "test-key"}):
        req = ChatCompletionRequest(
            model="minimax-m3:cloud",
            messages=[ChatMessage(role="user", content="hi")],
            stream=False,
        )
        await gateway.chat_completions_nonstream(req)

    forwarded = mock_client.request.call_args.kwargs["json"]
    assert "max_tokens" not in forwarded


@pytest.mark.asyncio
async def test_chat_completions_forwards_image_content_parts_to_upstream(ollama_gateway):
    gateway, mock_client = ollama_gateway

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
    }
    mock_client.request = AsyncMock(return_value=response)
    content = [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQSkZJRg==", "detail": "high"}},
    ]

    with patch.dict("os.environ", {"OLLAMA_CLOUD_API_KEY": "test-key"}):
        req = ChatCompletionRequest(
            model="minimax-m3:cloud",
            messages=[ChatMessage(role="user", content=content)],
            stream=False,
        )
        await gateway.chat_completions_nonstream(req)

    forwarded = mock_client.request.call_args.kwargs["json"]
    assert forwarded["messages"] == [{"role": "user", "content": content}]


@pytest.mark.asyncio
async def test_chat_completions_forwards_max_tokens(ollama_gateway):
    gateway, mock_client = ollama_gateway

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
    }
    mock_client.request = AsyncMock(return_value=response)

    with patch.dict("os.environ", {"OLLAMA_CLOUD_API_KEY": "test-key"}):
        req = ChatCompletionRequest(
            model="minimax-m3:cloud",
            messages=[ChatMessage(role="user", content="hi")],
            stream=False,
            extra={"max_tokens": 256},
        )
        await gateway.chat_completions_nonstream(req)

    forwarded = mock_client.request.call_args.kwargs["json"]
    assert forwarded["max_tokens"] == 256


@pytest.fixture
def openrouter_gateway():
    provider = ProviderSettings(
        name="openrouter",
        type="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
    )
    gateway = OpenAICompatibleGateway(provider, timeout=30.0)
    mock_client = AsyncMock()
    gateway._client = mock_client
    return gateway, mock_client


@pytest.mark.asyncio
async def test_responses_create_projects_reasoning_summary(openrouter_gateway):
    gateway, mock_client = openrouter_gateway
    thinking = "raw thinking"
    responses_response = MagicMock()
    responses_response.status_code = 200
    responses_response.json.return_value = {
        "id": "resp_or",
        "output": [
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [],
                "content": [{"type": "reasoning_text", "text": thinking}],
            }
        ],
    }
    mock_client.request = AsyncMock(return_value=responses_response)

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        result = await gateway.responses_create({"model": "minimax/minimax-m3", "input": "hi"})

    assert result["output"][0]["summary"] == [{"type": "summary_text", "text": thinking}]
    assert result["output"][0]["content"] == [{"type": "reasoning_text", "text": thinking}]


@pytest.mark.asyncio
async def test_responses_stream_rewrites_reasoning_text_events(openrouter_gateway):
    gateway, mock_client = openrouter_gateway
    event = (
        b"event: response.reasoning_text.delta\n"
        b'data: {"type":"response.reasoning_text.delta","item_id":"rs_1",'
        b'"output_index":0,"content_index":0,"delta":"Thinking"}\n\n'
    )

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_bytes(self):
            yield event

    mock_client.stream = MagicMock(return_value=FakeStream())

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        parts: list[bytes] = []
        async for chunk in gateway.responses_create_stream({"model": "minimax/minimax-m3", "input": "hi"}):
            parts.append(chunk)

    text = b"".join(parts).decode("utf-8")
    assert "event: response.reasoning_summary_text.delta" in text
    assert "response.reasoning_text.delta" not in text.replace("reasoning_summary_text", "")
    assert "Thinking" in text


_CHAT_OK = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
}


async def _forwarded_chat_json(gateway_fixture, env_key: str, req: ChatCompletionRequest, capabilities=None):
    """Send one non-stream Chat call and return the JSON body the upstream received."""
    gateway, mock_client = gateway_fixture
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _CHAT_OK
    mock_client.request = AsyncMock(return_value=response)
    show_response = MagicMock()
    show_response.status_code = 200
    show_response.json.return_value = {"capabilities": capabilities or ["completion"]}
    mock_client.post = AsyncMock(return_value=show_response)

    with patch.dict("os.environ", {env_key: "test-key"}):
        await gateway.chat_completions_nonstream(req)

    return mock_client.request.call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_chat_completions_forwards_the_client_fields_and_adds_no_temperature(ollama_gateway):
    req = ChatCompletionRequest(
        model="minimax-m3:cloud",
        messages=[ChatMessage(role="assistant", content="hi", extra={"reasoning_details": [{"type": "x"}]})],
        extra={"response_format": {"type": "json_object"}, "parallel_tool_calls": False, "stop": ["END"]},
    )

    forwarded = await _forwarded_chat_json(ollama_gateway, "OLLAMA_CLOUD_API_KEY", req)

    assert forwarded == {
        "model": "minimax-m3:cloud",
        "messages": [{"role": "assistant", "content": "hi", "reasoning_details": [{"type": "x"}]}],
        "stream": False,
        "response_format": {"type": "json_object"},
        "parallel_tool_calls": False,
        "stop": ["END"],
    }


@pytest.mark.asyncio
async def test_chat_completions_gives_ollama_max_tokens_when_only_max_completion_tokens_is_sent(ollama_gateway):
    req = ChatCompletionRequest(
        model="minimax-m3:cloud",
        messages=[ChatMessage(role="user", content="hi")],
        extra={"max_completion_tokens": 256},
    )

    forwarded = await _forwarded_chat_json(ollama_gateway, "OLLAMA_CLOUD_API_KEY", req)

    assert forwarded["max_completion_tokens"] == 256
    assert forwarded["max_tokens"] == 256


@pytest.mark.asyncio
async def test_chat_completions_keeps_the_max_tokens_the_client_sent_to_ollama(ollama_gateway):
    req = ChatCompletionRequest(
        model="minimax-m3:cloud",
        messages=[ChatMessage(role="user", content="hi")],
        extra={"max_completion_tokens": 256, "max_tokens": 64},
    )

    forwarded = await _forwarded_chat_json(ollama_gateway, "OLLAMA_CLOUD_API_KEY", req)

    assert forwarded["max_tokens"] == 64


@pytest.mark.asyncio
async def test_chat_completions_sends_openrouter_only_the_token_limit_the_client_sent(openrouter_gateway):
    req = ChatCompletionRequest(
        model="openai/o9",
        messages=[ChatMessage(role="user", content="hi")],
        extra={"max_completion_tokens": 256},
    )

    forwarded = await _forwarded_chat_json(openrouter_gateway, "OPENROUTER_API_KEY", req)

    assert forwarded["max_completion_tokens"] == 256
    assert "max_tokens" not in forwarded


@pytest.mark.asyncio
async def test_chat_completions_drops_reasoning_effort_for_an_ollama_model_that_cannot_think(ollama_gateway):
    req = ChatCompletionRequest(
        model="chat-no-think:cloud",
        messages=[ChatMessage(role="user", content="hi")],
        extra={"reasoning_effort": "high"},
    )

    forwarded = await _forwarded_chat_json(ollama_gateway, "OLLAMA_CLOUD_API_KEY", req, ["completion"])

    assert "reasoning_effort" not in forwarded


@pytest.mark.asyncio
async def test_chat_completions_keeps_reasoning_effort_for_an_ollama_model_that_thinks(ollama_gateway):
    req = ChatCompletionRequest(
        model="chat-thinker:cloud",
        messages=[ChatMessage(role="user", content="hi")],
        extra={"reasoning_effort": "high"},
    )

    forwarded = await _forwarded_chat_json(
        ollama_gateway, "OLLAMA_CLOUD_API_KEY", req, ["completion", "thinking"]
    )

    assert forwarded["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_chat_completions_drops_an_unknown_reasoning_effort_for_ollama(ollama_gateway):
    req = ChatCompletionRequest(
        model="chat-thinker-two:cloud",
        messages=[ChatMessage(role="user", content="hi")],
        extra={"reasoning_effort": "extreme"},
    )

    forwarded = await _forwarded_chat_json(
        ollama_gateway, "OLLAMA_CLOUD_API_KEY", req, ["completion", "thinking"]
    )

    assert "reasoning_effort" not in forwarded


@pytest.mark.asyncio
async def test_chat_completions_sends_openrouter_the_reasoning_effort_as_sent(openrouter_gateway):
    req = ChatCompletionRequest(
        model="openai/o9",
        messages=[ChatMessage(role="user", content="hi")],
        extra={"reasoning_effort": "extreme"},
    )

    forwarded = await _forwarded_chat_json(openrouter_gateway, "OPENROUTER_API_KEY", req)

    assert forwarded["reasoning_effort"] == "extreme"


@pytest.mark.asyncio
async def test_chat_stream_always_asks_the_upstream_for_usage(openrouter_gateway):
    gateway, mock_client = openrouter_gateway

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_bytes(self):
            yield b"data: [DONE]\n\n"

    mock_client.stream = MagicMock(return_value=FakeStream())
    req = ChatCompletionRequest(
        model="openai/o9",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
        extra={"stream_options": {"include_usage": False, "include_obfuscation": False}},
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        async for _ in gateway.chat_completions_stream(req):
            pass

    forwarded = mock_client.stream.call_args.kwargs["json"]
    assert forwarded["stream_options"] == {"include_usage": True, "include_obfuscation": False}
