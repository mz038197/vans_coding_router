"""A Personal API Key lists and calls follow the holder's Router Model Template."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router

TEXT_FIRST = "openrouter@z-text"
TEXT_SECOND = "ollama_cloud@a-text"
IMAGE_FIRST = "openrouter@z-image"
IMAGE_SECOND = "ollama_cloud@a-image"
SPEECH_FIRST = "openrouter@z-speech"
SPEECH_SECOND = "openai@a-speech"
TRANSCRIPTION_ID = "openai@gpt-transcribe"
DECISION_FIRST = "openrouter@z-decision"
DECISION_SECOND = "openrouter@a-decision"
CATALOG_CHAT = "catalog-chat"
CATALOG_IMAGE = "catalog-image"


def _client(tmp_path) -> tuple[TestClient, SqliteRouterRepository, FakeLLMGateway]:
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    gateway = FakeLLMGateway()
    gateway.models_response = {
        "object": "list",
        "data": [{"id": CATALOG_CHAT, "object": "model"}],
    }
    gateway.images_models_response = {
        "object": "list",
        "data": [{"id": CATALOG_IMAGE, "object": "model"}],
    }
    gateway.catalog_reads = 0
    original_models = gateway.models
    original_images = gateway.images_models

    async def models(*args, **kwargs):
        gateway.catalog_reads += 1
        return await original_models(*args, **kwargs)

    async def images_models(*args, **kwargs):
        gateway.catalog_reads += 1
        return await original_images(*args, **kwargs)

    gateway.models = models
    gateway.images_models = images_models
    app = FastAPI()
    register_error_handlers(app)
    auth = AuthUseCase(api_key_repo=repo)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth)
    app.include_router(create_api_router(ApiUseCase(gateway=gateway, api_key_repo=repo, logger=FakeRequestLogger())))
    return TestClient(app), repo, gateway


def _model(model_id: str, **flags: bool) -> dict:
    return {"id": model_id, "name": model_id, **flags}


def _personal_key(repo: SqliteRouterRepository, document: list[dict]) -> str:
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    repo.save_router_model_template(teacher["id"], document)
    return repo.issue_long_lived_key(teacher["id"])


def _ids(payload: dict) -> list[str]:
    return [item["id"] for item in payload["data"]]


def test_personal_key_lists_follow_each_template_shelf(tmp_path):
    client, repo, gateway = _client(tmp_path)
    api_key = _personal_key(
        repo,
        [
            {
                "name": "Later",
                "models": [
                    _model(TEXT_FIRST),
                    _model(IMAGE_FIRST, imageShelf=True),
                    _model(SPEECH_FIRST, speechShelf=True),
                    _model(DECISION_FIRST, decisionShelf=True),
                ],
            },
            {
                "name": "Earlier",
                "models": [
                    _model(TEXT_SECOND),
                    _model(IMAGE_SECOND, imageShelf=True),
                    _model(SPEECH_SECOND, speechShelf=True),
                    _model(TRANSCRIPTION_ID, speechTranscriptionShelf=True),
                    _model(DECISION_SECOND, decisionShelf=True),
                ],
            },
        ],
    )
    headers = {"Authorization": f"Bearer {api_key}"}

    assert _ids(client.get("/v1/models", headers=headers).json()) == [
        "vcr-auto",
        TEXT_FIRST,
        TEXT_SECOND,
    ]
    assert _ids(client.get("/v1/images/models", headers=headers).json()) == [
        "vcr-auto",
        IMAGE_FIRST,
        IMAGE_SECOND,
    ]
    assert _ids(client.get("/v1/audio/speech/models", headers=headers).json()) == [
        "vcr-auto",
        SPEECH_FIRST,
        SPEECH_SECOND,
    ]
    assert _ids(client.get("/v1/audio/transcriptions/models", headers=headers).json()) == [
        "vcr-auto",
        TRANSCRIPTION_ID,
    ]
    assert _ids(client.get("/v1/decisions/models", headers=headers).json()) == [
        "vcr-auto",
        DECISION_FIRST,
        DECISION_SECOND,
    ]
    assert CATALOG_CHAT not in client.get("/v1/models", headers=headers).text
    assert CATALOG_IMAGE not in client.get("/v1/images/models", headers=headers).text
    assert gateway.catalog_reads == 0


def test_personal_key_list_names_vcr_auto_once(tmp_path):
    client, repo, _gateway = _client(tmp_path)
    api_key = _personal_key(
        repo,
        [{"name": "VCRouter", "models": [_model("vcr-auto"), _model(TEXT_FIRST)]}],
    )
    listed = client.get("/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    assert _ids(listed.json()) == ["vcr-auto", TEXT_FIRST]


def _shelf_document() -> list[dict]:
    return [
        {
            "name": "VCRouter",
            "models": [
                _model(TEXT_FIRST),
                _model(TEXT_SECOND),
                _model(IMAGE_FIRST, imageShelf=True),
                _model(SPEECH_FIRST, speechShelf=True),
                _model(TRANSCRIPTION_ID, speechTranscriptionShelf=True),
                _model(DECISION_FIRST, decisionShelf=True),
            ],
        }
    ]


def test_personal_key_accepts_vcr_auto_or_a_model_on_that_shelf(tmp_path):
    client, repo, gateway = _client(tmp_path)
    headers = {"Authorization": f"Bearer {_personal_key(repo, _shelf_document())}"}

    chat = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": TEXT_SECOND, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert chat.status_code == 200
    assert gateway.last_nonstream_req is not None
    assert gateway.last_nonstream_req.model == TEXT_SECOND

    auto_chat = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "vcr-auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert auto_chat.status_code == 200
    assert auto_chat.json()["model"] == "vcr-auto"
    assert gateway.last_nonstream_req.model == TEXT_FIRST

    responses = client.post(
        "/v1/responses",
        headers=headers,
        json={"model": TEXT_FIRST, "input": "hi"},
    )
    assert responses.status_code == 200
    assert gateway.last_responses_body["model"] == TEXT_FIRST

    image = client.post(
        "/v1/images",
        headers=headers,
        json={"model": IMAGE_FIRST, "prompt": "cat"},
    )
    assert image.status_code == 200
    assert gateway.last_images_body["model"] == IMAGE_FIRST

    auto_image = client.post(
        "/v1/images",
        headers=headers,
        json={"model": "vcr-auto", "prompt": "cat"},
    )
    assert auto_image.status_code == 200
    assert gateway.last_images_body["model"] == IMAGE_FIRST

    speech = client.post(
        "/v1/audio/speech",
        headers=headers,
        json={"model": SPEECH_FIRST, "input": "hi", "voice": "alloy"},
    )
    assert speech.status_code == 200
    assert gateway.last_audio_speech_body["model"] == SPEECH_FIRST

    transcription = client.post(
        "/v1/audio/transcriptions",
        headers=headers,
        data={"model": TRANSCRIPTION_ID},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert transcription.status_code == 200
    assert gateway.last_audio_transcriptions_fields["model"] == TRANSCRIPTION_ID

    decision = client.post(
        "/v1/decisions",
        headers=headers,
        json={"model": DECISION_FIRST, "state": "now", "questions": [{"id": "q", "prompt": "?"}]},
    )
    assert decision.status_code == 200
    assert gateway.last_decision_body["model"] == DECISION_FIRST

    off_shelf = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": IMAGE_FIRST, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert off_shelf.status_code == 403
    assert off_shelf.json()["error"]["code"] == "model_not_allowed"

    unknown = client.post(
        "/v1/images",
        headers=headers,
        json={"model": "openrouter@not-on-the-shelf", "prompt": "cat"},
    )
    assert unknown.status_code == 403
    assert unknown.json()["error"]["code"] == "model_not_allowed"
    assert gateway.last_images_body["model"] == IMAGE_FIRST


def test_personal_key_empty_shelf_lists_nothing_and_refuses_the_call(tmp_path):
    client, repo, gateway = _client(tmp_path)
    headers = {"Authorization": f"Bearer {_personal_key(repo, [{"name": "VCRouter", "models": []}])}"}

    chat_list = client.get("/v1/models", headers=headers)
    image_list = client.get("/v1/images/models", headers=headers)
    speech_list = client.get("/v1/audio/speech/models", headers=headers)
    transcription_list = client.get("/v1/audio/transcriptions/models", headers=headers)
    decision_list = client.get("/v1/decisions/models", headers=headers)
    assert chat_list.status_code == 200
    assert image_list.status_code == 200
    assert speech_list.status_code == 200
    assert transcription_list.status_code == 200
    assert decision_list.status_code == 200
    assert _ids(chat_list.json()) == []
    assert _ids(image_list.json()) == []
    assert _ids(speech_list.json()) == []
    assert _ids(transcription_list.json()) == []
    assert _ids(decision_list.json()) == []
    assert gateway.catalog_reads == 0

    chat = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "vcr-auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert chat.status_code == 403
    assert chat.json()["error"]["code"] == "model_not_allowed"

    named = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": TEXT_FIRST, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert named.status_code == 403
    image = client.post(
        "/v1/images",
        headers=headers,
        json={"model": "vcr-auto", "prompt": "cat"},
    )
    assert image.status_code == 403
    assert image.json()["error"]["code"] == "image_generation_disabled"
    speech = client.post(
        "/v1/audio/speech",
        headers=headers,
        json={"model": SPEECH_FIRST, "input": "hi", "voice": "alloy"},
    )
    assert speech.status_code == 403
    assert speech.json()["error"]["code"] == "tts_disabled"
    transcription = client.post(
        "/v1/audio/transcriptions",
        headers=headers,
        data={"model": "vcr-auto"},
        files={"file": ("speech.wav", b"RIFF....", "audio/wav")},
    )
    assert transcription.status_code == 403
    assert transcription.json()["error"]["code"] == "speech_transcription_disabled"
    decision = client.post(
        "/v1/decisions",
        headers=headers,
        json={"model": "vcr-auto", "state": "now", "questions": [{"id": "q", "prompt": "?"}]},
    )
    assert decision.status_code == 403
    assert decision.json()["error"]["code"] == "decision_disabled"
    assert gateway.last_nonstream_req is None
    assert gateway.last_images_body is None
    assert gateway.last_decision_body is None
