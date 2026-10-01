"""Classroom Model Choice selects which student calls and lists a sitting accepts."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from src.presentation.fastapi.routers.portal_router import create_portal_router

TEXT_ID = "ollama_cloud@sitting-text:cloud"
IMAGE_ID = "openrouter@black-forest-labs/flux.2-pro"
SPEECH_ID = "openrouter@speech-model"
TRANSCRIPTION_ID = "openrouter@transcribe-model"
DECISION_ID = "openrouter@typesafe/jev-1.13"


def _client(tmp_path) -> tuple[TestClient, SqliteRouterRepository]:
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-session-secret",
            dev_auth_enabled=True,
        ),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    register_error_handlers(app)
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=FakeLLMGateway(), api_key_repo=repo, logger=FakeRequestLogger())
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    app.include_router(create_portal_router(PortalUseCase(repo, settings), settings))
    client = TestClient(app, base_url="http://127.0.0.1", headers={"Origin": settings.public_url})
    return client, repo


def _portal_cookie(repo, user_id: int) -> dict[str, str]:
    token, _ = repo.create_portal_session(user_id, "Test browser")
    return {"vcr_portal_session": token}


def _sitting(client, repo, *, choice: str | None = "automatic"):
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=[
            {
                "name": "VCRouter",
                "vendor": "customendpoint",
                "apiType": "responses",
                "models": [
                    {"id": TEXT_ID, "name": "text"},
                    {"id": IMAGE_ID, "name": "flux", "imageShelf": True},
                    {"id": SPEECH_ID, "name": "speech", "speechShelf": True},
                    {"id": TRANSCRIPTION_ID, "name": "transcribe", "speechTranscriptionShelf": True},
                    {"id": DECISION_ID, "name": "jev", "decisionShelf": True},
                ],
            }
        ],
    )
    if choice is None:
        with repo._connect() as conn:
            conn.execute(
                repo._sql("UPDATE class_sessions SET classroom_model_choice = NULL WHERE id = ?"),
                (session["id"],),
            )
    elif choice != "automatic":
        repo.update_class_session(klass["id"], session["id"], classroom_model_choice=choice)
    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={"handoff_token": login.json()["handoff_token"], "invite_code": session["invite_code"]},
    )
    return redeem.json()["api_key"], teacher, klass, session


def _ids(payload: dict) -> list[str]:
    return [item["id"] for item in payload["data"]]


def test_new_session_starts_automatic_and_cannot_return_to_mixed(tmp_path):
    client, repo = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    cookies = _portal_cookie(repo, teacher["id"])
    created = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "Week 1"},
    )
    assert created.status_code == 200
    assert created.json()["classroom_model_choice"] == "automatic"
    session_id = created.json()["id"]

    picked = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"classroom_model_choice": "picked"},
    )
    assert picked.status_code == 200
    assert picked.json()["classroom_model_choice"] == "picked"

    cleared = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"classroom_model_choice": None},
    )
    assert cleared.status_code == 400
    assert client.get(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
    ).json()["items"][0]["classroom_model_choice"] == "picked"


def test_automatic_chat_accepts_only_vcr_auto(tmp_path):
    client, repo = _client(tmp_path)
    api_key, *_ = _sitting(client, repo, choice="automatic")
    headers = {"Authorization": f"Bearer {api_key}"}

    listed = client.get("/v1/models", headers=headers)
    assert _ids(listed.json()) == ["vcr-auto"]
    vscode = client.get("/extension/chat-language-models", headers=headers)
    assert [model["id"] for model in vscode.json()[0]["models"]] == ["vcr-auto"]
    assert TEXT_ID not in vscode.text
    assert DECISION_ID not in vscode.text

    named = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": TEXT_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert named.status_code == 403
    assert named.json()["error"]["code"] == "model_not_allowed"
    auto = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "vcr-auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert auto.status_code == 200


def test_picked_chat_lists_text_models_and_refuses_vcr_auto(tmp_path):
    client, repo = _client(tmp_path)
    api_key, teacher, klass, session = _sitting(client, repo, choice="picked")
    headers = {"Authorization": f"Bearer {api_key}"}

    assert _ids(client.get("/v1/models", headers=headers).json()) == [TEXT_ID]
    vscode = client.get("/extension/chat-language-models", headers=headers)
    assert [model["id"] for model in vscode.json()[0]["models"]] == [TEXT_ID]
    assert DECISION_ID not in vscode.text

    named = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": TEXT_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert named.status_code == 200
    auto = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "vcr-auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert auto.status_code == 403
    decision = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": DECISION_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert decision.status_code == 403

    student = repo.get_user_by_email("student@gmail.com")
    script = client.get(
        "/portal/download/install-vscode-models.ps1",
        cookies=_portal_cookie(repo, student["id"]),
        headers=headers,
    )
    assert script.status_code == 200
    assert TEXT_ID in script.text
    assert "vcr-auto" not in script.text
    assert DECISION_ID not in script.text
    del teacher, klass, session


def test_unset_choice_keeps_mixed_chat(tmp_path):
    client, repo = _client(tmp_path)
    api_key, *_ = _sitting(client, repo, choice=None)
    headers = {"Authorization": f"Bearer {api_key}"}
    assert _ids(client.get("/v1/models", headers=headers).json()) == ["vcr-auto"]
    named = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": TEXT_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert named.status_code == 200
    auto = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "vcr-auto", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert auto.status_code == 200


def test_image_speech_transcription_and_decision_follow_the_choice(tmp_path):
    client, repo = _client(tmp_path)
    api_key, *_ = _sitting(client, repo, choice="picked")
    headers = {"Authorization": f"Bearer {api_key}"}

    assert _ids(client.get("/v1/images/models", headers=headers).json()) == [IMAGE_ID]
    assert _ids(client.get("/v1/audio/speech/models", headers=headers).json()) == [SPEECH_ID]
    assert _ids(client.get("/v1/audio/transcriptions/models", headers=headers).json()) == [TRANSCRIPTION_ID]
    assert _ids(client.get("/v1/decisions/models", headers=headers).json()) == [DECISION_ID]

    image = client.post("/v1/images", headers=headers, json={"model": "vcr-auto", "prompt": "cat"})
    assert image.status_code == 403
    speech = client.post(
        "/v1/audio/speech",
        headers=headers,
        json={"model": SPEECH_ID, "input": "hi", "voice": "alloy"},
    )
    assert speech.status_code == 200
    decision = client.post(
        "/v1/decisions",
        headers=headers,
        json={"model": "vcr-auto", "state": {}, "questions": [{"id": "q", "prompt": "?"}]},
    )
    assert decision.status_code == 403

    api_key, teacher, klass, session = _sitting(client, repo, choice="automatic")
    headers = {"Authorization": f"Bearer {api_key}"}
    assert _ids(client.get("/v1/images/models", headers=headers).json()) == ["vcr-auto"]
    assert _ids(client.get("/v1/audio/speech/models", headers=headers).json()) == ["vcr-auto"]
    assert _ids(client.get("/v1/decisions/models", headers=headers).json()) == ["vcr-auto"]
    named_image = client.post(
        "/v1/images",
        headers=headers,
        json={"model": IMAGE_ID, "prompt": "cat"},
    )
    assert named_image.status_code == 403
    auto_decision = client.post(
        "/v1/decisions",
        headers=headers,
        json={"model": "vcr-auto", "state": {}, "questions": [{"id": "q", "prompt": "?"}]},
    )
    assert auto_decision.status_code == 200
    del teacher, klass, session


def test_empty_speech_decision_lists_still_succeed(tmp_path):
    client, repo = _client(tmp_path)
    api_key, *_ = _sitting(client, repo, choice="automatic")
    teacher = repo.get_user_by_email("teacher@school.edu")
    # Replace the sitting document with text only, leaving the other shelves empty.
    session = repo.list_class_sessions(repo.list_classes(teacher_id=teacher["id"])[0]["id"])[0]
    repo.update_class_session(
        session["class_id"],
        session["id"],
        session_chat_language_models=[
            {"name": "VCRouter", "vendor": "customendpoint", "models": [{"id": TEXT_ID, "name": "text"}]}
        ],
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    speech = client.get("/v1/audio/speech/models", headers=headers)
    decision = client.get("/v1/decisions/models", headers=headers)
    assert speech.status_code == 200
    assert _ids(speech.json()) == ["vcr-auto"]
    assert decision.status_code == 200
    assert _ids(decision.json()) == ["vcr-auto"]
    images = client.get("/v1/images/models", headers=headers)
    assert images.status_code == 403
    refused = client.post(
        "/v1/audio/speech",
        headers=headers,
        json={"model": "vcr-auto", "input": "hi", "voice": "alloy"},
    )
    assert refused.status_code == 403
