from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger
from infrastructure.test_routing_gateway import FakeGateway
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router

_DECISION_BODY = {
    "model": "openrouter@typesafe/jev-1.13",
    "state": "付款失敗三天了",
    "questions": {
        "urgent": {
            "type": "noul",
            "instructions": "這則訊息急迫嗎？",
        }
    },
}


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


def _student_key(repo: SqliteRouterRepository) -> tuple[dict, dict, str]:
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    return klass, session, redeem["api_key"]


def _openrouter_document(*model_ids: str, decision_ids: tuple[str, ...] = ()) -> list[dict]:
    marked = set(decision_ids)
    return [
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "models": [
                {
                    "id": model_id,
                    "name": model_id,
                    **({"decisionShelf": True} if model_id in marked else {}),
                }
                for model_id in model_ids
            ],
        }
    ]


def _set_decision_model(repo, klass, session, model_id: str, extra_ids: tuple[str, ...] = ()) -> None:
    ids = (model_id, *extra_ids) if model_id else tuple(extra_ids)
    decision_ids = (model_id,) if model_id else ()
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=_openrouter_document(*ids, decision_ids=decision_ids) if ids else [],
    )


def test_decision_off_refuses_before_upstream(tmp_path):
    client, repo, gateway, _logger = _sqlite_api_client(tmp_path)
    _klass, session, student_key = _student_key(repo)

    assert session["decision_model"] == ""
    blocked = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "decision_disabled"
    assert gateway.last_decision_body is None


def _sqlite_routing_client(tmp_path):
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    openrouter = FakeGateway("openrouter")
    routing = RoutingGateway({"openrouter": openrouter, "ollama_cloud": FakeGateway("ollama_cloud")})
    logger = FakeRequestLogger()
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=routing, api_key_repo=repo, logger=logger)
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    return TestClient(app), repo, openrouter


def test_allowed_decision_forwards_state_and_questions_only(tmp_path):
    client, repo, openrouter = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    openrouter.decision_response = {
        "id": "gen-dec-1",
        "model": "typesafe/jev-1.13-20260917",
        "provider": "TypeSafe",
        "answers": {"urgent": {"type": "noul", "noul": 0.91}},
        "usage": {"input_tokens": 275, "output_tokens": 20, "cost": 0.00003},
    }

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={
            **_DECISION_BODY,
            "provider": {"order": ["somewhere"]},
            "user": "student",
            "trace": {"trace_id": "t-1"},
            "sessionId": "sess-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == openrouter.decision_response
    assert openrouter.last_decision_body == {
        "model": "typesafe/jev-1.13",
        "state": "付款失敗三天了",
        "questions": _DECISION_BODY["questions"],
    }


def test_decision_model_mismatch_refuses_before_upstream(tmp_path):
    client, repo, openrouter = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(
        repo,
        klass,
        session,
        "openrouter@~typesafe/jev-latest",
        extra_ids=("openrouter@typesafe/jev-1.13",),
    )

    blocked = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )

    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "model_not_allowed"
    assert openrouter.last_decision_body is None


def test_reply_model_does_not_authorize_the_next_decision(tmp_path):
    client, repo, openrouter = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@~typesafe/jev-latest")
    headers = {"Authorization": f"Bearer {student_key}"}
    openrouter.decision_response = {
        "id": "gen-dec-1",
        "model": "typesafe/jev-1.13-20260917",
        "answers": {"urgent": {"type": "noul", "noul": 0.91}},
        "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0},
    }

    first = client.post(
        "/v1/decisions",
        headers=headers,
        json={**_DECISION_BODY, "model": "openrouter@~typesafe/jev-latest"},
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/decisions",
        headers=headers,
        json={**_DECISION_BODY, "model": "openrouter@typesafe/jev-1.13-20260917"},
    )
    assert second.status_code == 403
    assert second.json()["error"]["code"] == "model_not_allowed"
    assert openrouter.last_decision_body["model"] == "~typesafe/jev-latest"


def test_decision_refusal_returns_provider_message(tmp_path):
    from src.domain.errors import UpstreamServiceError

    client, repo, openrouter = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    openrouter.decision_error = UpstreamServiceError(
        status_code=400,
        backend="openrouter",
        body={"error": {"message": "questions must include type"}},
    )

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["message"] == "questions must include type"
    assert "choices" not in body
    assert "output_text" not in response.text


def test_stale_decision_model_treated_as_off(tmp_path):
    client, repo, openrouter = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=_openrouter_document("openrouter@minimax/minimax-m3"),
    )

    blocked = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "decision_disabled"
    assert openrouter.last_decision_body is None


def test_previously_stored_single_choice_does_not_enable_decision(tmp_path):
    client, repo, gateway, _logger = _sqlite_api_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=_openrouter_document("openrouter@typesafe/jev-1.13"),
        decision_model="openrouter@typesafe/jev-1.13",
    )

    blocked = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "decision_disabled"
    assert gateway.last_decision_body is None


def test_every_decision_shelf_model_can_receive_a_decision_request(tmp_path):
    client, repo, openrouter = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=_openrouter_document(
            "openrouter@typesafe/jev-1.13",
            "openrouter@~typesafe/jev-latest",
            decision_ids=(
                "openrouter@typesafe/jev-1.13",
                "openrouter@~typesafe/jev-latest",
            ),
        ),
    )
    openrouter.decision_response = {
        "id": "gen-dec-2",
        "model": "typesafe/jev-latest",
        "answers": {"urgent": {"type": "noul", "noul": 0.5}},
        "usage": {"input_tokens": 1, "output_tokens": 1, "cost": 0},
    }

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={**_DECISION_BODY, "model": "openrouter@~typesafe/jev-latest"},
    )
    assert response.status_code == 200
    assert openrouter.last_decision_body["model"] == "~typesafe/jev-latest"


def test_legacy_decision_columns_do_not_enable_decision(tmp_path):
    client, repo, gateway, _logger = _sqlite_api_client(tmp_path)
    _klass, session, student_key = _student_key(repo)
    with repo._connect() as conn:
        conn.execute(
            "UPDATE class_sessions SET decision_enabled = 1, decision_model_allowlist_json = ? WHERE id = ?",
            ('["openrouter@typesafe/jev-1.13"]', session["id"]),
        )

    listed = repo.list_class_sessions(_klass["id"])
    assert listed[0]["decision_model"] == ""
    blocked = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "decision_disabled"
    assert gateway.last_decision_body is None
