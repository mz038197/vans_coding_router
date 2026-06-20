from src.domain.errors import UpstreamServiceError

from api_test_utils import build_test_client
from fakes import FakeApiKeyRepository


def test_health_endpoint_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert "queue_waiting" in payload
    assert "backends" in payload


def test_models_endpoint_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.get("/v1/models", headers={"Authorization": "Bearer valid-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    assert isinstance(payload["data"], list)
    assert payload["data"][0]["id"] == "fake-model"


def test_models_endpoint_rejects_when_api_key_missing(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.get("/v1/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_models_endpoint_allows_missing_api_key_when_key_system_disabled(fake_gateway, fake_logger):
    disabled_repo = FakeApiKeyRepository(config_data={}, force_enabled=False)
    client = build_test_client(disabled_repo, fake_gateway, fake_logger)

    response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json()["object"] == "list"


def test_chat_completion_rejects_when_api_key_missing(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "fake-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 401
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["message"] == "無效的 API 金鑰"
    assert "detail" not in payload
    assert len(fake_logger.entries) > 0
    last_entry = fake_logger.entries[-1]
    assert last_entry["is_valid"] is False


def test_chat_completion_rejects_when_api_key_invalid(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer invalid-key"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 401
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["message"] == "無效的 API 金鑰"
    assert "detail" not in payload
    # 驗證無效的認證嘗試被記錄到審計追蹤
    assert len(fake_logger.entries) > 0
    # 檢查最後一次記錄是無效的認證
    last_entry = fake_logger.entries[-1]
    assert last_entry["is_valid"] is False
    assert last_entry["api_key"] == "invalid-key"


def test_chat_completion_nonstream_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": "hello"}], "stream": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert "choices" in payload
    assert "usage" in payload
    assert payload["choices"][0]["message"]["role"] == "assistant"


def test_chat_completion_stream_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    ) as response:
        body = b"".join(response.iter_bytes()).decode("utf-8")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "data: [DONE]" in body


def test_chat_completion_upstream_error_nonstream_openai_format(fake_repo, fake_gateway, fake_logger):
    async def failing_nonstream(_req):
        raise UpstreamServiceError(
            status_code=502,
                backend="openrouter",
            body="upstream failed",
        )

    fake_gateway.chat_completions_nonstream = failing_nonstream
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": "hello"}], "stream": False},
    )
    assert response.status_code == 502
    payload = response.json()
    assert payload["error"]["message"] == "Upstream provider error"
    assert payload["error"]["type"] == "server_error"
    assert "detail" not in payload


def test_chat_completion_upstream_error_stream_openai_sse(fake_repo, fake_gateway, fake_logger):
    async def failing_stream(_req):
        raise UpstreamServiceError(
            status_code=502,
                backend="openrouter",
            body="upstream failed",
        )
        yield b""  # pragma: no cover

    fake_gateway.chat_completions_stream = failing_stream
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    ) as response:
        body = b"".join(response.iter_bytes()).decode("utf-8")
        assert response.status_code == 200
        assert "choices" in body
        assert "Upstream provider error" in body
        assert "data: [DONE]" in body


def test_chat_completion_rejects_empty_content(fake_repo, fake_gateway, fake_logger):
    """驗證 content 不能為空字符串 - API 契約強制執行非空內容。"""
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": ""}]},
    )
    # Pydantic 驗證失敗應返回 422 Unprocessable Entity
    assert response.status_code == 422
    payload = response.json()
    assert "detail" in payload


def test_chat_completion_rejects_null_content(fake_repo, fake_gateway, fake_logger):
    """驗證 content 不能為 null - API 契約不允許可選的內容欄位。"""
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": None}]},
    )
    # Pydantic 驗證失敗應返回 422 Unprocessable Entity
    assert response.status_code == 422
    payload = response.json()
    assert "detail" in payload


def test_chat_completion_with_openai_text_format(fake_repo, fake_gateway, fake_logger):
    """驗證支援 OpenAI 相容格式 - content 是包含 text 物件的陣列"""
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "fake-model",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "What is this?"}],
                }
            ],
            "stream": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["choices"][0]["message"]["role"] == "assistant"


def test_chat_completion_with_openai_image_format(fake_repo, fake_gateway, fake_logger):
    """驗證支援 OpenAI 相容格式 - content 包含文字和影像"""
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "fake-model",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQSkZJRg=="},
                        },
                    ],
                }
            ],
            "stream": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert fake_gateway.last_nonstream_req is not None
    assert fake_gateway.last_nonstream_req.messages[0].images == ["/9j/4AAQSkZJRg=="]


def test_chat_completion_with_simple_text_format(fake_repo, fake_gateway, fake_logger):
    """驗證向後相容性 - content 仍可以是簡單字符串"""
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "fake-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"


def test_chat_completion_forwards_tools_to_gateway(fake_repo, fake_gateway, fake_logger):
    """驗證 tools / tool_choice 會傳入 use case 與 gateway（domain 請求）。"""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "天氣",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "fake-model",
            "messages": [{"role": "user", "content": "台北天氣"}],
            "stream": False,
            "tools": tools,
            "tool_choice": "auto",
        },
    )
    assert response.status_code == 200
    assert fake_gateway.last_nonstream_req is not None
    assert fake_gateway.last_nonstream_req.tools == tools
    assert fake_gateway.last_nonstream_req.tool_choice == "auto"


def test_chat_completion_accepts_assistant_with_tool_calls_only(fake_repo, fake_gateway, fake_logger):
    """驗證 OpenAI 風格：assistant 僅含 tool_calls 時可通過驗證。"""
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "fake-model",
            "messages": [
                {"role": "user", "content": "查天氣"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"TPE"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "25C"},
            ],
            "stream": False,
        },
    )
    assert response.status_code == 200
    assert fake_gateway.last_nonstream_req is not None
    msgs = fake_gateway.last_nonstream_req.messages
    assert msgs[1].tool_calls is not None
    assert msgs[2].role == "tool"
    assert msgs[2].tool_call_id == "call_1"
