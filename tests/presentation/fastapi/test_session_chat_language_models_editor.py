from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.domain.session_model_allowlist import VCROUTER_STENCIL
from src.infrastructure.config import (
    CAPABILITY_AUDIO_SPEECH,
    CAPABILITY_AUDIO_TRANSCRIPTION,
    AuthSettings,
    DatabaseSettings,
    ProviderSettings,
    RouterSettings,
)
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from src.presentation.fastapi.routers.portal_router import create_portal_router


def _classroom_providers() -> dict[str, ProviderSettings]:
    return {
        "ollama_cloud": ProviderSettings(
            name="ollama_cloud",
            enabled=True,
            base_url="https://ollama.test/v1",
        ),
        "openrouter": ProviderSettings(
            name="openrouter",
            enabled=True,
            base_url="https://openrouter.test/v1",
        ),
        "openai": ProviderSettings(
            name="openai",
            enabled=True,
            base_url="https://api.openai.com/v1",
            capabilities=(CAPABILITY_AUDIO_SPEECH, CAPABILITY_AUDIO_TRANSCRIPTION),
        ),
    }


def _catalog_gateway() -> RoutingGateway:
    ollama = FakeLLMGateway()
    ollama.models_response = {
        "object": "list",
        "data": [{"id": "minimax-m3:cloud", "name": "minimax-m3"}],
    }
    openrouter = FakeLLMGateway()
    openrouter.models_response = {
        "object": "list",
        "data": [{"id": "minimax/minimax-m3", "name": "minimax-m3"}],
    }
    openai = FakeLLMGateway()
    openai.models_response = {
        "object": "list",
        "data": [{"id": "gpt-4o-mini-tts", "name": "tts"}],
    }
    return RoutingGateway(
        {
            "ollama_cloud": ollama,
            "openrouter": openrouter,
            "openai": openai,
        }
    )


class _FailingModelsGateway:
    async def models(self):
        raise RuntimeError("upstream /models down")


def _settings(tmp_path, providers=None) -> RouterSettings:
    return RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-session-secret",
            dev_auth_enabled=True,
        ),
        providers=providers or {},
    )


def _client(tmp_path, *, llm_gateway=None, providers=None):
    settings = _settings(tmp_path, providers=providers)
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    register_error_handlers(app)
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(
        gateway=FakeLLMGateway(),
        api_key_repo=repo,
        logger=FakeRequestLogger(),
    )
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    app.include_router(
        create_portal_router(PortalUseCase(repo, settings, llm_gateway=llm_gateway), settings)
    )
    return (
        TestClient(
            app,
            base_url="http://127.0.0.1",
            headers={"Origin": settings.public_url},
        ),
        repo,
        settings,
    )


def _portal_cookie(repo, user_id: int) -> dict[str, str]:
    token, _ = repo.create_portal_session(user_id, "Test browser")
    return {"vcr_portal_session": token}


def _redeem_student_key(client, invite_code: str) -> str:
    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={"handoff_token": login.json()["handoff_token"], "invite_code": invite_code},
    )
    return redeem.json()["api_key"]


def _owner_session(repo):
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    return teacher, klass, session


def test_teacher_get_returns_session_chat_language_models(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher, klass, session = _owner_session(repo)
    response = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    assert response.status_code == 200
    assert response.json()["session_chat_language_models"] == load_vans_template()


def test_owner_and_admin_can_save_session_document_other_teacher_cannot(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher, klass, session = _owner_session(repo)
    admin = repo.upsert_google_user("admin@school.edu", "Admin")
    other = repo.upsert_google_user("other@school.edu", "Other")
    document = [
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "models": [
                {
                    "id": "ollama_cloud@minimax-m3:cloud",
                    "name": "sitting-only",
                    "url": "https://evil.example/v1",
                    "thinking": False,
                    "maxInputTokens": 111,
                    "maxOutputTokens": 22,
                }
            ],
        }
    ]

    forbidden = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, other["id"]),
        json={"session_chat_language_models": document},
    )
    assert forbidden.status_code == 403

    by_owner = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"session_chat_language_models": document},
    )
    assert by_owner.status_code == 200
    saved = by_owner.json()["session_chat_language_models"]
    assert saved[0]["name"] == "VCRouter"
    assert saved[0]["vendor"] == "customendpoint"
    assert saved[0]["apiType"] == "responses"
    model = saved[0]["models"][0]
    assert model["id"] == "ollama_cloud@minimax-m3:cloud"
    assert model["name"] == "sitting-only"
    assert model["url"] == VCROUTER_STENCIL["url"]
    assert model["requestHeaders"] == VCROUTER_STENCIL["requestHeaders"]
    assert model["thinking"] is False
    assert model["maxInputTokens"] == 111

    by_admin = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, admin["id"]),
        json={"session_chat_language_models": []},
    )
    assert by_admin.status_code == 200
    assert by_admin.json()["session_chat_language_models"][0]["models"] == []


def test_invalid_upload_is_rejected_and_stored_document_is_unchanged(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher, klass, session = _owner_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])
    before = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
    ).json()["session_chat_language_models"]

    rejected = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
        json={"session_chat_language_models": {"name": "not-an-array"}},
    )
    assert rejected.status_code == 400

    missing_id = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
        json={"session_chat_language_models": [{"name": "VCRouter", "models": [{"name": "x"}]}]},
    )
    assert missing_id.status_code == 400

    after = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
    ).json()["session_chat_language_models"]
    assert after == before == load_vans_template()


def test_student_keyed_get_and_chat_follow_saved_document(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher, klass, session = _owner_session(repo)
    document = [
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "models": [{"id": "ollama_cloud@minimax-m3:cloud", "name": "sitting-only"}],
        }
    ]
    saved = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"session_chat_language_models": document},
    )
    assert saved.status_code == 200
    api_key = _redeem_student_key(client, session["invite_code"])

    keyed = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert keyed.status_code == 200
    ids = [model["id"] for model in keyed.json()[0]["models"]]
    assert ids == ["ollama_cloud@minimax-m3:cloud"]
    assert keyed.json()[0]["models"][0]["url"] == VCROUTER_STENCIL["url"]

    allowed = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": "ollama_cloud@minimax-m3:cloud", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert allowed.status_code == 200
    blocked = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": "openrouter@minimax/minimax-m3", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert blocked.status_code == 403


def test_empty_document_means_zero_chat_models_on_keyed_get_and_v1(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher, klass, session = _owner_session(repo)
    emptied = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"session_chat_language_models": []},
    )
    assert emptied.status_code == 200
    assert emptied.json()["session_chat_language_models"][0]["models"] == []
    api_key = _redeem_student_key(client, session["invite_code"])

    keyed = client.get(
        "/extension/chat-language-models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert keyed.json()[0]["models"] == []

    blocked = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": "ollama_cloud@minimax-m3:cloud", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "model_not_allowed"


def test_upstream_model_catalog_lists_chat_providers_and_excludes_speech_only(tmp_path):
    client, repo, _ = _client(
        tmp_path,
        llm_gateway=_catalog_gateway(),
        providers=_classroom_providers(),
    )
    teacher, _, _ = _owner_session(repo)
    response = client.get(
        "/teacher/upstream-model-catalog",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable"] is False
    assert set(body["providers"]) == {"ollama_cloud", "openrouter"}
    ids = [item["id"] for item in body["models"]]
    assert "ollama_cloud@minimax-m3:cloud" in ids
    assert "openrouter@minimax/minimax-m3" in ids
    assert all(not item["id"].startswith("openai@") for item in body["models"])
    assert ids.count("ollama_cloud@minimax-m3:cloud") == 1
    assert ids.count("openrouter@minimax/minimax-m3") == 1


def test_catalog_fetch_failure_does_not_clear_stored_rows(tmp_path):
    client, repo, _ = _client(
        tmp_path,
        llm_gateway=_FailingModelsGateway(),
        providers=_classroom_providers(),
    )
    teacher, klass, session = _owner_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])
    stored = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
    )
    assert stored.status_code == 200
    assert stored.json()["session_chat_language_models"] == load_vans_template()

    catalog = client.get("/teacher/upstream-model-catalog", cookies=cookies)
    assert catalog.status_code == 200
    assert catalog.json()["unavailable"] is True
    assert catalog.json()["models"] == []
    assert stored.json()["session_chat_language_models"][0]["models"]


def test_portal_session_row_shows_session_chat_language_models_editor(tmp_path):
    client, _, _ = _client(tmp_path)
    html = client.get("/portal").text
    assert "<th>模型</th>" in html
    assert 'id="editSessionChatModelsModal"' in html
    assert "beginEditSessionChatLanguageModels" in html
    assert "downloadSessionChatModelsTemplate" in html
    assert "downloadCurrentSessionChatModels" in html
    assert "sessionChatModelsDropzone" in html
    assert "session_chat_language_models" in html
    assert 'id="sessionChatModelsJson"' not in html
    assert "下載範本" in html
    assert "下載目前清單" in html
