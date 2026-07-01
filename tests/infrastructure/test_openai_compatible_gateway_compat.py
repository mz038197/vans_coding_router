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
async def test_chat_completions_forwards_resolved_max_tokens(ollama_gateway):
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
            max_tokens=256,
        )
        await gateway.chat_completions_nonstream(req)

    forwarded = mock_client.request.call_args.kwargs["json"]
    assert forwarded["max_tokens"] == 256
