"""Embeddings requests follow the embeddings shelf the way image generation follows its shelf."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_test_utils import build_test_client
from fakes import FakeLLMGateway, FakeRequestLogger
from infrastructure.test_routing_gateway import FakeGateway
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.domain.errors import UpstreamServiceError
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router

EMBEDDINGS_ID = "openrouter@openai/text-embedding-3-small"
TEXT_ID = "ollama_cloud@sitting-text:cloud"
UPSTREAM_MODEL = "openai/text-embedding-3-small"
VECTOR = [0.25, -0.5]


def _routing_client(fake_repo, fake_logger):
    ollama = FakeGateway("ollama_cloud")
    openrouter = FakeGateway("openrouter")
    routing = RoutingGateway({"ollama_cloud": ollama, "openrouter": openrouter})
    return build_test_client(fake_repo, routing, fake_logger), openrouter


def _sqlite_api_client(tmp_path):
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    gateway = FakeLLMGateway()
    gateway.embeddings_response = {
        "object": "list",
        "model": UPSTREAM_MODEL,
        "data": [{"object": "embedding", "index": 0, "embedding": VECTOR}],
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }
    logger = FakeRequestLogger()
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=gateway, api_key_repo=repo, logger=logger)
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    return TestClient(app), repo, gateway


def _sitting(repo, *, choice: str | None = "automatic", models: list | None = None):
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    document_models = models if models is not None else [
        {"id": TEXT_ID, "name": "text"},
        {"id": EMBEDDINGS_ID, "name": "embed", "embeddingsShelf": True},
    ]
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=[
            {"name": "VCRouter", "vendor": "customendpoint", "models": document_models}
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
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    return teacher, klass, session, {"Authorization": f"Bearer {redeem['api_key']}"}


def _ids(payload: dict) -> list[str]:
    return [item["id"] for item in payload["data"]]


def test_embeddings_request_forwards_the_body_and_keeps_the_upstream_model(fake_repo, fake_logger):
    client, openrouter = _routing_client(fake_repo, fake_logger)
    response = client.post(
        "/v1/embeddings",
        headers={"Authorization": "Bearer valid-key"},
        json={
            "model": EMBEDDINGS_ID,
            "input": "a blue robot",
            "dimensions": 256,
        },
    )
    assert response.status_code == 200
    assert response.json()["model"] == "openai/text-embedding-3-small"
    assert response.json()["data"][0]["embedding"] == [0.25, -0.5]
    assert openrouter.last_embeddings_body["model"] == "openai/text-embedding-3-small"
    assert openrouter.last_embeddings_body["input"] == "a blue robot"
    assert openrouter.last_embeddings_body["dimensions"] == 256


def test_classroom_embeddings_follow_the_shelf(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    _teacher, _klass, _session, headers = _sitting(repo, choice=None, models=[])
    body = {"model": EMBEDDINGS_ID, "input": "cat"}

    blocked = client.post("/v1/embeddings", headers=headers, json=body)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "embeddings_disabled"
    assert gateway.last_embeddings_body is None
    assert client.get("/v1/embeddings/models", headers=headers).status_code == 403

    _teacher, klass, session, headers = _sitting(repo, choice=None)
    ok = client.post("/v1/embeddings", headers=headers, json={**body, "dimensions": 8})
    assert ok.status_code == 200
    assert ok.json()["model"] == UPSTREAM_MODEL
    assert gateway.last_embeddings_body["model"] == EMBEDDINGS_ID
    assert gateway.last_embeddings_body["dimensions"] == 8
    listed = client.get("/v1/embeddings/models", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"] == [{"id": "vcr-auto", "object": "model"}]
    wrong = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": "openrouter@other/embed", "input": "cat"},
    )
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "model_not_allowed"
    chat = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert chat.status_code == 403
    models = client.get("/v1/models", headers=headers)
    assert EMBEDDINGS_ID not in models.text
    del klass, session


def test_automatic_and_picked_embeddings_follow_classroom_model_choice(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    teacher, klass, _session, headers = _sitting(repo, choice="automatic")
    named = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "input": "cat"},
    )
    assert named.status_code == 403
    assert _ids(client.get("/v1/embeddings/models", headers=headers).json()) == ["vcr-auto"]
    auto = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": "vcr-auto", "input": "cat"},
    )
    assert auto.status_code == 200
    assert auto.json()["model"] == UPSTREAM_MODEL
    assert gateway.last_embeddings_body["model"] == EMBEDDINGS_ID
    logs = repo.list_prompt_logs(teacher["id"], klass["id"])
    assert logs[0]["model"] == EMBEDDINGS_ID

    _teacher, _klass, _session, headers = _sitting(repo, choice="picked")
    assert _ids(client.get("/v1/embeddings/models", headers=headers).json()) == [EMBEDDINGS_ID]
    refused_auto = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": "vcr-auto", "input": "cat"},
    )
    assert refused_auto.status_code == 403
    picked = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "input": "cat"},
    )
    assert picked.status_code == 200
    chat_models = client.get("/v1/models", headers=headers)
    assert _ids(chat_models.json()) == [TEXT_ID]


def test_embeddings_prompt_log_stores_text_and_a_stand_in_for_the_reply(tmp_path):
    client, repo, _gateway = _sqlite_api_client(tmp_path)
    teacher, klass, session, headers = _sitting(repo, choice="picked")
    logged = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "input": ["alpha", "beta"]},
    )
    assert logged.status_code == 200
    logs = repo.list_prompt_logs(teacher["id"], klass["id"])
    assert len(logs) == 1
    assert logs[0]["model"] == EMBEDDINGS_ID
    assert "alpha" in logs[0]["raw_prompt"]
    assert "beta" in logs[0]["raw_prompt"]
    assert "0.25" not in logs[0]["raw_prompt"]
    assert "已產生嵌入" in (logs[0]["response_preview"] or "")
    assert "0.25" not in (logs[0]["response_preview"] or "")

    tokens = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "input": [11, 22]},
    )
    assert tokens.status_code == 200
    logs = repo.list_prompt_logs(teacher["id"], klass["id"])
    assert len(logs) == 2
    assert "［非文字嵌入輸入］" in logs[0]["raw_prompt"] or "［非文字嵌入輸入］" in logs[1]["raw_prompt"]
    assert "11" not in logs[0]["raw_prompt"]
    assert "11" not in logs[1]["raw_prompt"]

    repo.update_class_session(klass["id"], session["id"], prompt_logging_enabled=False)
    quiet = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "input": "hidden"},
    )
    assert quiet.status_code == 200
    assert len(repo.list_prompt_logs(teacher["id"], klass["id"])) == 2


def test_embeddings_refusal_is_the_provider_refusal(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    teacher, klass, _session, headers = _sitting(repo, choice="picked")
    gateway.embeddings_error = UpstreamServiceError(
        status_code=402,
        backend="openrouter",
        body={"error": {"message": "Insufficient credits"}},
    )
    refused = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "input": "cat"},
    )
    assert refused.status_code == 402
    assert refused.json()["error"]["message"] == "Insufficient credits"
    assert "Upstream provider error" not in refused.text
    assert repo.list_prompt_logs(teacher["id"], klass["id"]) == []


def test_personal_api_key_embeddings_follow_the_holder_template(tmp_path):
    client, repo, gateway = _sqlite_api_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    repo.save_router_model_template(
        teacher["id"],
        [
            {
                "name": "VCRouter",
                "models": [{"id": EMBEDDINGS_ID, "name": "embed", "embeddingsShelf": True}],
            }
        ],
    )
    headers = {"Authorization": f"Bearer {repo.issue_long_lived_key(teacher['id'])}"}
    listed = client.get("/v1/embeddings/models", headers=headers)
    assert _ids(listed.json()) == ["vcr-auto", EMBEDDINGS_ID]
    response = client.post(
        "/v1/embeddings",
        headers=headers,
        json={"model": EMBEDDINGS_ID, "input": "teacher"},
    )
    assert response.status_code == 200
    assert gateway.last_embeddings_body["input"] == "teacher"
    empty_teacher = repo.upsert_google_user("empty@school.edu", "Empty")
    repo.update_user(empty_teacher["id"], roles=["teacher"])
    repo.save_router_model_template(empty_teacher["id"], [{"name": "VCRouter", "models": []}])
    empty_headers = {"Authorization": f"Bearer {repo.issue_long_lived_key(empty_teacher['id'])}"}
    empty_list = client.get("/v1/embeddings/models", headers=empty_headers)
    assert empty_list.status_code == 200
    assert empty_list.json()["data"] == []
    refused = client.post(
        "/v1/embeddings",
        headers=empty_headers,
        json={"model": "vcr-auto", "input": "nope"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "embeddings_disabled"
