from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from fakes import FakeApiKeyRepository, FakeLLMGateway, FakeRequestLogger
from src.domain.entities.chat import ChatCompletionRequest, ChatMessage


@pytest.fixture
def fake_repo() -> FakeApiKeyRepository:
    return FakeApiKeyRepository(
        config_data={
            "TeacherA": {
                "api_keys": [
                    {"name": "ClassA", "key": "valid-key", "enabled": True},
                    {"name": "ClassB", "key": "disabled-key", "enabled": False},
                ]
            }
        },
        force_enabled=True,
    )


@pytest.fixture
def fake_logger() -> FakeRequestLogger:
    return FakeRequestLogger()


@pytest.fixture
def fake_gateway() -> FakeLLMGateway:
    return FakeLLMGateway()


@pytest.fixture
def sample_chat_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="fake-model",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
        temperature=0.7,
        max_tokens=16,
    )
