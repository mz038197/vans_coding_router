import pytest

from src.application.use_cases.api_use_case import ApiUseCase


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
