import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_test_utils import build_test_client
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
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
    routing = RoutingGateway({"ollama_cloud": ollama, "openrouter": openrouter})
    return build_test_client(fake_repo, routing, fake_logger)


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


def test_images_create_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/images",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "openrouter@black-forest-labs/flux.2-pro",
            "prompt": "a blue robot icon",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["b64_json"] == "abc123"
    assert fake_gateway.last_images_body["model"] == "openrouter@black-forest-labs/flux.2-pro"
    assert fake_gateway.last_images_body["prompt"] == "a blue robot icon"


def test_images_create_rejects_invalid_api_key(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/images",
        json={"model": "openrouter@flux.2-pro", "prompt": "test"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_images_create_rejects_bare_model(fake_repo, fake_logger):
    client = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/images",
        headers={"Authorization": "Bearer valid-key"},
        json={"model": "flux.2-pro", "prompt": "test"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["param"] == "model"


def test_images_create_stream_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.post(
        "/v1/images",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": "openrouter@black-forest-labs/flux.2-pro",
            "prompt": "stream test",
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert fake_gateway.last_images_body["stream"] is True


def test_images_models_contract(fake_repo, fake_gateway, fake_logger):
    client = build_test_client(fake_repo, fake_gateway, fake_logger)
    response = client.get(
        "/v1/images/models",
        headers={"Authorization": "Bearer valid-key"},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "flux.2-pro"


def _check_image_shelf(repo, klass, session, model_id: str) -> None:
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=[
            {
                "name": "VCRouter",
                "vendor": "customendpoint",
                "models": [{"id": model_id, "name": model_id, "imageShelf": True}],
            }
        ],
    )


def test_classroom_image_generation_follows_the_image_shelf(tmp_path):
    client, repo, gateway, _logger = _sqlite_api_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    headers = {"Authorization": f"Bearer {redeem['api_key']}"}
    body = {"model": "openrouter@black-forest-labs/flux.2-pro", "prompt": "cat"}

    assert repo.is_image_generation_enabled(session["id"]) is True
    blocked = client.post("/v1/images", headers=headers, json=body)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "image_generation_disabled"
    assert gateway.last_images_body is None

    blocked_models = client.get("/v1/images/models", headers=headers)
    assert blocked_models.status_code == 403

    _check_image_shelf(repo, klass, session, "openrouter@black-forest-labs/flux.2-pro")
    ok = client.post("/v1/images", headers=headers, json=body)
    assert ok.status_code == 200
    assert gateway.last_images_body["model"] == "openrouter@black-forest-labs/flux.2-pro"

    listed = client.get("/v1/images/models", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"] == [{"id": "vcr-auto", "object": "model"}]

    wrong = client.post(
        "/v1/images",
        headers=headers,
        json={"model": "openrouter@other/flux", "prompt": "cat"},
    )
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "model_not_allowed"
    assert gateway.last_images_body["model"] == "openrouter@black-forest-labs/flux.2-pro"


def test_teacher_long_lived_key_bypasses_session_image_toggle(tmp_path):
    client, repo, _gateway, _logger = _sqlite_api_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    teacher_key = repo.issue_long_lived_key(teacher["id"])
    repo.update_class_session(klass["id"], session["id"], image_generation_enabled=False)

    response = client.post(
        "/v1/images",
        headers={"Authorization": f"Bearer {teacher_key}"},
        json={"model": "openrouter@black-forest-labs/flux.2-pro", "prompt": "teacher test"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ollama_provider_forwards_images(monkeypatch):
    from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway
    from src.infrastructure.config import ProviderSettings

    gateway = OpenAICompatibleGateway(
        ProviderSettings(name="ollama_cloud", type="openai_compatible", base_url="https://ollama.com/v1"),
    )
    seen: dict = {}

    async def fake_request(method, path, **kwargs):
        seen["method"] = method
        seen["path"] = path
        seen["json"] = kwargs.get("json")
        return httpx.Response(200, json={"created": 1, "data": []})

    monkeypatch.setattr(gateway, "_request", fake_request)
    result = await gateway.images_create({"model": "x/z-image-turbo", "prompt": "test"})
    assert seen == {
        "method": "POST",
        "path": "/images",
        "json": {"model": "x/z-image-turbo", "prompt": "test"},
    }
    assert result["data"] == []
