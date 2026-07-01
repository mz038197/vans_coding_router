import json

import pytest

from src.application.use_cases.api_use_case import ApiUseCase
from src.domain.entities.auth import AuthContext
from fakes import FakeApiKeyRepository, FakeLLMGateway, FakeRequestLogger


class CapturingPromptRepo(FakeApiKeyRepository):
    def __init__(self, *, prompt_logging_enabled: bool = True):
        super().__init__(force_enabled=False)
        self.prompts: list[dict] = []
        self.prompt_logging_enabled = prompt_logging_enabled

    def log_prompt(self, **kwargs) -> None:
        self.prompts.append(kwargs)

    def is_prompt_logging_enabled(self, session_id: int) -> bool:
        return self.prompt_logging_enabled


@pytest.mark.asyncio
async def test_chat_nonstream_persists_assistant_reply_and_endpoint(sample_chat_request):
    repo = CapturingPromptRepo()
    use_case = ApiUseCase(gateway=FakeLLMGateway(), api_key_repo=repo, logger=FakeRequestLogger())

    await use_case.chat_nonstream(sample_chat_request, None)

    assert len(repo.prompts) == 1
    prompt = repo.prompts[0]
    assert prompt["api_endpoint"] == "/v1/chat/completions"
    assert prompt["response_preview"] == "hello"
    messages = json.loads(prompt["messages_json"])
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "hello"


@pytest.mark.asyncio
async def test_responses_create_persists_assistant_reply_and_endpoint():
    repo = CapturingPromptRepo()
    use_case = ApiUseCase(gateway=FakeLLMGateway(), api_key_repo=repo, logger=FakeRequestLogger())

    await use_case.responses_create({"model": "fake-model", "input": "hi"}, None)

    assert len(repo.prompts) == 1
    prompt = repo.prompts[0]
    assert prompt["api_endpoint"] == "/v1/responses"
    assert prompt["response_preview"] == "hello"


@pytest.mark.asyncio
async def test_chat_nonstream_skips_prompt_log_when_session_logging_disabled(sample_chat_request):
    repo = CapturingPromptRepo(prompt_logging_enabled=False)
    gateway = FakeLLMGateway()
    gateway.nonstream_response = {
        **gateway.nonstream_response,
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    use_case = ApiUseCase(gateway=gateway, api_key_repo=repo, logger=FakeRequestLogger())
    auth = AuthContext(
        user_id=1,
        email="student@school.edu",
        name="Student",
        session_id=42,
        class_id=7,
    )

    await use_case.chat_nonstream(sample_chat_request, "valid-key", auth_context=auth)

    assert repo.prompts == []


@pytest.mark.asyncio
async def test_health_and_models_delegate_to_gateway(fake_repo, fake_logger, fake_gateway):
    use_case = ApiUseCase(gateway=fake_gateway, api_key_repo=fake_repo, logger=fake_logger)
    assert await use_case.health() == fake_gateway.health_response
    assert await use_case.models() == fake_gateway.models_response


@pytest.mark.asyncio
async def test_chat_nonstream_logs_and_returns_gateway_response(
    fake_repo, fake_logger, fake_gateway, sample_chat_request
):
    use_case = ApiUseCase(gateway=fake_gateway, api_key_repo=fake_repo, logger=fake_logger)

    data = await use_case.chat_nonstream(sample_chat_request, "valid-key")

    assert data == fake_gateway.nonstream_response
    assert fake_gateway.last_nonstream_req == sample_chat_request
    assert len(fake_logger.entries) == 1
    assert fake_logger.entries[0]["teacher_name"] == "TeacherA"
    assert fake_logger.entries[0]["is_valid"] is True


@pytest.mark.asyncio
async def test_chat_stream_logs_and_yields_chunks(fake_repo, fake_logger, fake_gateway, sample_chat_request):
    use_case = ApiUseCase(gateway=fake_gateway, api_key_repo=fake_repo, logger=fake_logger)

    chunks = []
    async for chunk in use_case.chat_stream(sample_chat_request, "valid-key"):
        chunks.append(chunk)

    assert chunks == fake_gateway.stream_chunks
    assert fake_gateway.last_stream_req == sample_chat_request
    assert len(fake_logger.entries) == 1
    assert fake_logger.entries[0]["is_valid"] is True


@pytest.mark.asyncio
async def test_chat_nonstream_logs_invalid_key_when_enabled(fake_repo, fake_logger, fake_gateway, sample_chat_request):
    use_case = ApiUseCase(gateway=fake_gateway, api_key_repo=fake_repo, logger=fake_logger)

    await use_case.chat_nonstream(sample_chat_request, "invalid-key")

    assert fake_logger.entries[0]["teacher_name"] is None
    assert fake_logger.entries[0]["is_valid"] is False
