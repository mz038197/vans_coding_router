import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_test_utils import build_test_client
from fakes import FakeLLMGateway, FakeRequestLogger
from infrastructure.test_routing_gateway import FakeGateway
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.domain.errors import SpeechTranscriptionNotSupportedError
from src.infrastructure.config import (
    AuthSettings,
    CAPABILITY_AUDIO_TRANSCRIPTION,
    DatabaseSettings,
    ProviderSettings,
    RouterSettings,
)
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router


def _routing_client(fake_repo, fake_logger):
    ollama = FakeGateway("ollama_cloud")
    openrouter = FakeGateway("openrouter")
    openai = FakeGateway("openai", (CAPABILITY_AUDIO_TRANSCRIPTION,))
    routing = RoutingGateway({"ollama_cloud": ollama, "openrouter": openrouter, "openai": openai})
    return build_test_client(fake_repo, routing, fake_logger), openai


def _sqlite_api_client(tmp_path) -> tuple[TestClient, SqliteRouterRepository, FakeLLMGateway, FakeRequestLogger]:
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    gateway = FakeLLMGateway()
    logger = FakeRequestLogger()
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=gateway, api_key_repo=repo, logger=logger)
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    return TestClient(app), repo, gateway, logger


def test_audio_transcriptions_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer valid-key"},
        data={"model": "openai@gpt-transcribe"},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "hello from audio"
    assert fake_gateway.last_audio_transcriptions_fields["model"] == "openai@gpt-transcribe"
    assert fake_gateway.last_audio_transcriptions_file == ("speech.wav", b"RIFF....", "audio/wav")


def test_audio_transcriptions_stream_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer valid-key"},
        data={"model": "openai@gpt-transcribe", "stream": "true"},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"transcript.text.delta" in response.content
    assert fake_gateway.last_audio_transcriptions_fields["model"] == "openai@gpt-transcribe"


def test_audio_transcriptions_rejects_invalid_api_key(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/audio/transcriptions",
        data={"model": "openai@gpt-transcribe"},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_audio_transcriptions_rejects_bare_model(fake_repo, fake_logger):
    client, _openai = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer valid-key"},
        data={"model": "gpt-transcribe"},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "model"


def test_audio_transcriptions_rejects_unsupported_provider(fake_repo, fake_logger):
    client, _openai = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": "Bearer valid-key"},
        data={"model": "openrouter@gpt-transcribe"},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "speech_transcription_not_supported"


def test_session_speech_transcription_toggle_blocks_and_reopens(tmp_path):
    client, repo, gateway, _logger = _sqlite_api_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    student_key = redeem["api_key"]
    headers = {"Authorization": f"Bearer {student_key}"}
    data = {"model": "openai@gpt-transcribe"}
    files = {"file": ("speech.wav", b"RIFF....", "audio/wav")}

    assert repo.is_speech_transcription_enabled(session["id"]) is False
    blocked = client.post("/v1/audio/transcriptions", headers=headers, data=data, files=files)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "speech_transcription_disabled"

    repo.update_class_session(klass["id"], session["id"], speech_transcription_enabled=True)
    ok = client.post("/v1/audio/transcriptions", headers=headers, data=data, files=files)
    assert ok.status_code == 200
    assert gateway.last_audio_transcriptions_fields["model"] == "openai@gpt-transcribe"

    repo.update_class_session(klass["id"], session["id"], speech_transcription_enabled=False)
    blocked_again = client.post("/v1/audio/transcriptions", headers=headers, data=data, files=files)
    assert blocked_again.status_code == 403


def test_teacher_long_lived_key_bypasses_speech_transcription_toggle(tmp_path):
    client, repo, _gateway, _logger = _sqlite_api_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    teacher_key = repo.issue_long_lived_key(teacher["id"])
    assert repo.is_speech_transcription_enabled(session["id"]) is False

    response = client.post(
        "/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {teacher_key}"},
        data={"model": "openai@gpt-transcribe"},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openai_compatible_rejects_audio_transcriptions_without_capability():
    gateway = OpenAICompatibleGateway(
        ProviderSettings(
            name="ollama_cloud",
            type="openai_compatible",
            base_url="https://ollama.com/v1",
        ),
    )
    with pytest.raises(SpeechTranscriptionNotSupportedError):
        await gateway.audio_transcriptions_create(
            {"model": "x"},
            ("speech.wav", b"RIFF....", "audio/wav"),
        )
