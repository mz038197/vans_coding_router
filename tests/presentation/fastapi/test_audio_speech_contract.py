from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_test_utils import build_test_client
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import AuthSettings, CAPABILITY_AUDIO_SPEECH, DatabaseSettings, RouterSettings
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from fakes import FakeLLMGateway, FakeRequestLogger
from infrastructure.test_routing_gateway import FakeGateway


def _routing_client(fake_repo, fake_logger):
    ollama = FakeGateway("ollama_cloud")
    openrouter = FakeGateway("openrouter")
    openai = FakeGateway("openai", (CAPABILITY_AUDIO_SPEECH,))
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


def test_audio_speech_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/audio/speech",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "openai@gpt-4o-mini-tts",
            "input": "你好",
            "voice": "nova",
            "response_format": "pcm",
        },
    )
    assert response.status_code == 200
    assert response.content == b"\x00\x01\x00\x02"
    assert response.headers["content-type"].startswith("audio/pcm")
    assert fake_gateway.last_audio_speech_body["model"] == "openai@gpt-4o-mini-tts"
    assert fake_gateway.last_audio_speech_body["input"] == "你好"


def test_audio_speech_rejects_invalid_api_key(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/audio/speech",
        json={
            "model": "openai@gpt-4o-mini-tts",
            "input": "test",
            "voice": "nova",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_audio_speech_rejects_bare_model(fake_repo, fake_logger):
    client, _openai = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/audio/speech",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "gpt-4o-mini-tts",
            "input": "test",
            "voice": "nova",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "model"


def test_audio_speech_forwards_a_provider_without_a_capability_flag(fake_repo, fake_logger):
    client, _openai = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/audio/speech",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "openrouter@gpt-4o-mini-tts",
            "input": "test",
            "voice": "nova",
        },
    )
    assert response.status_code == 200
    assert response.content == b"\x00\x01"


def test_session_tts_follows_the_speech_shelf(tmp_path):
    client, repo, gateway, _logger = _sqlite_api_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    headers = {"Authorization": f"Bearer {redeem['api_key']}"}
    body = {
        "model": "openai@gpt-4o-mini-tts",
        "input": "你好",
        "voice": "nova",
        "response_format": "pcm",
    }

    assert repo.is_tts_enabled(session["id"]) is True
    blocked = client.post("/v1/audio/speech", headers=headers, json=body)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "tts_disabled"
    assert gateway.last_audio_speech_body is None

    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=[
            {
                "name": "VCRouter",
                "vendor": "customendpoint",
                "models": [
                    {
                        "id": "openai@gpt-4o-mini-tts",
                        "name": "TTS",
                        "speechShelf": True,
                    }
                ],
            }
        ],
    )
    ok = client.post("/v1/audio/speech", headers=headers, json=body)
    assert ok.status_code == 200
    assert gateway.last_audio_speech_body["model"] == "openai@gpt-4o-mini-tts"

    wrong = client.post(
        "/v1/audio/speech",
        headers=headers,
        json={**body, "model": "openai@gpt-4o-mini-tts-other"},
    )
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "model_not_allowed"

