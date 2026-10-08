"""Classroom API Key model lists and the Portal install script name only vcr-auto."""

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


def _classroom_key(client, repo) -> tuple[str, dict, dict, dict]:
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
                    {
                        "id": "ollama_cloud@sitting-only:cloud",
                        "name": "sitting-only",
                        "url": "https://sitting.example/v1",
                        "requestHeaders": {"Authorization": "Bearer sitting"},
                        "thinking": False,
                        "toolCalling": False,
                        "vision": False,
                        "maxInputTokens": 8,
                        "maxOutputTokens": 4,
                    },
                    {
                        "id": "openrouter@black-forest-labs/flux.2-pro",
                        "name": "flux",
                        "imageShelf": True,
                        "thinking": False,
                        "vision": False,
                        "toolCalling": False,
                        "maxInputTokens": 1,
                        "maxOutputTokens": 1,
                    },
                    {
                        "id": "openrouter@openai/text-embedding-3-small",
                        "name": "embed",
                        "embeddingsShelf": True,
                        "thinking": False,
                        "vision": False,
                        "toolCalling": False,
                        "maxInputTokens": 1,
                        "maxOutputTokens": 1,
                    },
                ],
            }
        ],
    )
    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={"handoff_token": login.json()["handoff_token"], "invite_code": session["invite_code"]},
    )
    return redeem.json()["api_key"], teacher, klass, session


def test_classroom_key_model_lists_name_only_vcr_auto(tmp_path):
    client, repo = _client(tmp_path)
    api_key, teacher, _klass, _session = _classroom_key(client, repo)
    headers = {"Authorization": f"Bearer {api_key}"}

    models = client.get("/v1/models", headers=headers)
    assert models.status_code == 200
    assert [item["id"] for item in models.json()["data"]] == ["vcr-auto"]

    images = client.get("/v1/images/models", headers=headers)
    assert images.status_code == 200
    assert images.json()["data"] == [{"id": "vcr-auto", "object": "model"}]

    embeddings = client.get("/v1/embeddings/models", headers=headers)
    assert embeddings.status_code == 200
    assert embeddings.json()["data"] == [{"id": "vcr-auto", "object": "model"}]

    vscode = client.get("/extension/chat-language-models", headers=headers)
    assert vscode.status_code == 200
    document = vscode.json()
    assert len(document) == 1
    assert document[0]["name"] == "VCRouter"
    assert document[0]["vendor"] == "customendpoint"
    assert document[0]["apiType"] == "responses"
    assert [model["id"] for model in document[0]["models"]] == ["vcr-auto"]
    entry = document[0]["models"][0]
    assert entry["name"] == "vcr-auto"
    assert entry["vision"] is True
    assert entry["toolCalling"] is True
    assert entry["thinking"] is True
    assert entry["maxInputTokens"] == 262144
    assert entry["maxOutputTokens"] == 65536
    assert entry["url"] == "https://ai.vanscoding.com/v1"
    assert entry["requestHeaders"] == {"Authorization": "Bearer ${apiKey}"}
    assert "ollama_cloud@sitting-only:cloud" not in vscode.text
    assert "https://sitting.example/v1" not in vscode.text

    student = repo.get_user_by_email("student@gmail.com")
    script = client.get(
        "/portal/download/install-vscode-models.ps1",
        cookies=_portal_cookie(repo, student["id"]),
        headers=headers,
    )
    assert script.status_code == 200
    assert '"id": "vcr-auto"' in script.text
    assert '"name": "vcr-auto"' in script.text
    assert '"vision": true' in script.text
    assert '"toolCalling": true' in script.text
    assert '"thinking": true' in script.text
    assert '"maxInputTokens": 262144' in script.text
    assert '"maxOutputTokens": 65536' in script.text
    assert "https://ai.vanscoding.com/v1" in script.text
    assert "Bearer ${apiKey}" in script.text
    assert "ollama_cloud@sitting-only:cloud" not in script.text
    assert "openrouter@black-forest-labs/flux.2-pro" not in script.text

    personal = repo.issue_long_lived_key(teacher["id"])
    personal_headers = {"Authorization": f"Bearer {personal}"}
    personal_models = client.get("/v1/models", headers=personal_headers)
    assert personal_models.status_code == 200
    assert [item["id"] for item in personal_models.json()["data"]] == [
        "vcr-auto",
        "ollama_cloud@minimax-m3:cloud",
        "ollama_cloud@kimi-k2.7-code:cloud",
        "openrouter@minimax/minimax-m3",
    ]
    assert "fake-model" not in personal_models.text
    personal_images = client.get("/v1/images/models", headers=personal_headers)
    assert personal_images.status_code == 200
    assert personal_images.json()["data"] == []


def test_classroom_image_list_is_refused_when_the_image_shelf_is_empty(tmp_path):
    client, repo = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={"handoff_token": login.json()["handoff_token"], "invite_code": session["invite_code"]},
    )
    images = client.get(
        "/v1/images/models",
        headers={"Authorization": f"Bearer {redeem.json()['api_key']}"},
    )
    assert images.status_code == 403
    assert images.json()["error"]["code"] == "image_generation_disabled"
