import json

import pytest

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
    klass = repo.create_class(teacher["id"], "AI 素養", None)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    with repo._connect() as conn:
        conn.execute(
            repo._sql("UPDATE class_sessions SET classroom_model_choice = NULL WHERE id = ?"),
            (session["id"],),
        )
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
    assert blocked.json()["error"]["type"] == "invalid_request_error"
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
    ollama = FakeGateway("ollama_cloud")
    routing = RoutingGateway({"openrouter": openrouter, "ollama_cloud": ollama})
    logger = FakeRequestLogger()
    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=routing, api_key_repo=repo, logger=logger)
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    return TestClient(app), repo, openrouter, ollama


def test_checked_ollama_decision_model_is_forwarded(tmp_path):
    client, repo, openrouter, ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "ollama_cloud@kimi-k3:cloud")

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={**_DECISION_BODY, "model": "ollama_cloud@kimi-k3:cloud"},
    )

    assert response.status_code == 200
    assert ollama.last_decision_body == {
        "model": "kimi-k3:cloud",
        "state": "付款失敗三天了",
        "questions": _DECISION_BODY["questions"],
    }
    assert openrouter.last_decision_body is None


def test_allowed_decision_forwards_state_and_questions_only(tmp_path):
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
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


def test_vcr_auto_decision_forwards_state_and_questions_only(tmp_path):
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={
            **_DECISION_BODY,
            "model": "vcr-auto",
            "provider": {"order": ["somewhere"]},
            "user": "student",
            "trace": {"trace_id": "t-1"},
        },
    )

    assert response.status_code == 200
    assert openrouter.last_decision_body == {
        "model": "typesafe/jev-1.13",
        "state": "付款失敗三天了",
        "questions": _DECISION_BODY["questions"],
    }


def test_decision_model_mismatch_refuses_before_upstream(tmp_path):
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
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
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
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

    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
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
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
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
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
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


def test_personal_api_key_decision_forwards_a_template_shelf_model(tmp_path):
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    repo.save_router_model_template(
        teacher["id"],
        _openrouter_document(
            "openrouter@typesafe/jev-9.9",
            decision_ids=("openrouter@typesafe/jev-9.9",),
        ),
    )
    personal = repo.issue_long_lived_key(teacher["id"])
    openrouter.decision_response = {
        "id": "gen-dec-personal",
        "model": "typesafe/jev-9.9",
        "answers": {"urgent": {"type": "noul", "noul": 0.4}},
        "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0},
    }

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {personal}"},
        json={
            **_DECISION_BODY,
            "model": "openrouter@typesafe/jev-9.9",
            "provider": {"order": ["somewhere"]},
            "user": "teacher",
        },
    )

    assert response.status_code == 200
    assert response.json() == openrouter.decision_response
    assert openrouter.last_decision_body == {
        "model": "typesafe/jev-9.9",
        "state": "付款失敗三天了",
        "questions": _DECISION_BODY["questions"],
    }
    refused = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {personal}"},
        json={**_DECISION_BODY, "model": "openrouter@typesafe/jev-1.13"},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "model_not_allowed"


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


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (400, "invalid_request_error"),
        (413, "invalid_request_error"),
        (422, "invalid_request_error"),
        (402, "server_error"),
        (500, "server_error"),
    ],
)
def test_decision_refusal_type_follows_who_is_at_fault(tmp_path, status_code, error_type):
    from src.domain.errors import UpstreamServiceError

    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    openrouter.decision_error = UpstreamServiceError(
        status_code=status_code,
        backend="openrouter",
        body={"detail": {"error_type": "api_usage_error", "message": "Invalid image dimensions."}},
    )

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )

    assert response.status_code == status_code
    assert response.json()["error"]["type"] == error_type


def _teacher_of(repo) -> dict:
    return repo.upsert_google_user("teacher@school.edu", "Teacher")


def _usage_row(repo, klass, user_email: str) -> dict:
    user = repo.upsert_google_user(user_email, user_email.split("@")[0])
    return next(r for r in repo.class_usage(_teacher_of(repo)["id"], klass["id"]) if r["user_id"] == user["id"])


def test_successful_decision_stores_a_summary_prompt_log_and_token_usage(tmp_path):
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    openrouter.decision_response = {
        "id": "gen-dec-1",
        "model": "typesafe/jev-1.13-20260917",
        "answers": {"urgent": {"type": "noul", "noul": 0.91}},
        "usage": {"input_tokens": 275, "output_tokens": 20, "cost": 0.00003},
    }

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )

    assert response.status_code == 200
    logs = repo.list_prompt_logs(_teacher_of(repo)["id"], klass["id"])
    assert len(logs) == 1
    assert logs[0]["model"] == "openrouter@typesafe/jev-1.13"
    assert "付款失敗三天了" in logs[0]["raw_prompt"]
    assert "urgent：這則訊息急迫嗎？" in logs[0]["raw_prompt"]
    assert "noul" not in logs[0]["raw_prompt"]
    assert logs[0]["response_preview"] == "urgent：0.91"
    row = _usage_row(repo, klass, "student@school.edu")
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"], row["request_count"]) == (
        275,
        20,
        295,
        1,
    )


def test_decision_with_prompt_logging_off_records_usage_and_no_prompt_log(tmp_path):
    client, repo, _openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    repo.update_class_session(klass["id"], session["id"], prompt_logging_enabled=False)

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json=_DECISION_BODY,
    )

    assert response.status_code == 200
    assert repo.list_prompt_logs(_teacher_of(repo)["id"], klass["id"]) == []
    row = _usage_row(repo, klass, "student@school.edu")
    assert (row["total_tokens"], row["request_count"]) == (2, 1)


def test_decision_state_images_become_a_stand_in_and_objects_compact_json(tmp_path):
    client, repo, _openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    headers = {"Authorization": f"Bearer {student_key}"}

    with_image = client.post(
        "/v1/decisions",
        headers=headers,
        json={
            **_DECISION_BODY,
            "state": [
                "學生上傳的商品照片",
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAA"}},
            ],
        },
    )
    assert with_image.status_code == 200
    with_object = client.post(
        "/v1/decisions",
        headers=headers,
        json={**_DECISION_BODY, "state": {"訂單": 42, "狀態": "失敗"}},
    )
    assert with_object.status_code == 200

    logs = repo.list_prompt_logs(_teacher_of(repo)["id"], klass["id"])
    assert len(logs) == 2
    raw_prompts = "\n".join(log["raw_prompt"] for log in logs)
    details = [repo.get_prompt_log(_teacher_of(repo)["id"], klass["id"], log["id"]) for log in logs]
    stored = json.dumps([logs, details], ensure_ascii=False, default=str)
    assert "學生上傳的商品照片\n[圖片]" in raw_prompts
    assert '{"訂單":42,"狀態":"失敗"}' in raw_prompts
    assert "base64" not in stored
    assert "iVBORw0KGgo" not in stored


def test_vcr_auto_decision_records_the_model_id_that_produced_output(tmp_path):
    client, repo, _openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={**_DECISION_BODY, "model": "vcr-auto"},
    )

    assert response.status_code == 200
    logs = repo.list_prompt_logs(_teacher_of(repo)["id"], klass["id"])
    assert [log["model"] for log in logs] == ["openrouter@typesafe/jev-1.13"]


def test_refused_decisions_record_nothing(tmp_path):
    from src.domain.errors import UpstreamServiceError

    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    headers = {"Authorization": f"Bearer {student_key}"}

    decision_off = client.post("/v1/decisions", headers=headers, json=_DECISION_BODY)
    assert decision_off.status_code == 403
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    not_allowed = client.post(
        "/v1/decisions", headers=headers, json={**_DECISION_BODY, "model": "openrouter@other/model"}
    )
    assert not_allowed.status_code == 403
    openrouter.decision_error = UpstreamServiceError(
        status_code=400,
        backend="openrouter",
        body={"error": {"message": "questions must include type"}},
    )
    provider_refusal = client.post("/v1/decisions", headers=headers, json=_DECISION_BODY)
    assert provider_refusal.status_code == 400

    assert repo.list_prompt_logs(_teacher_of(repo)["id"], klass["id"]) == []
    row = _usage_row(repo, klass, "student@school.edu")
    assert (row["total_tokens"], row["request_count"]) == (0, 0)


def test_personal_api_key_decision_records_usage_without_a_class(tmp_path):
    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
    teacher = _teacher_of(repo)
    repo.update_user(teacher["id"], roles=["teacher"])
    repo.save_router_model_template(
        teacher["id"],
        _openrouter_document("openrouter@typesafe/jev-9.9", decision_ids=("openrouter@typesafe/jev-9.9",)),
    )
    personal = repo.issue_long_lived_key(teacher["id"])

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {personal}"},
        json={**_DECISION_BODY, "model": "openrouter@typesafe/jev-9.9"},
    )

    assert response.status_code == 200
    assert repo.delete_prompt_logs_for_users([teacher["id"]])["deleted_token_usage"] == 1


def test_a_long_decision_summary_is_cut_short_on_both_sides(tmp_path):
    from src.infrastructure.logging.message_preview import LOG_TRUNCATED_SUFFIX, RESPONSE_LOG_MAX_CHARS

    client, repo, openrouter, _ollama = _sqlite_routing_client(tmp_path)
    klass, session, student_key = _student_key(repo)
    _set_decision_model(repo, klass, session, "openrouter@typesafe/jev-1.13")
    long_text = "長" * (RESPONSE_LOG_MAX_CHARS + 50)
    openrouter.decision_response = {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {"urgent": {"type": "text", "text": long_text}},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    response = client.post(
        "/v1/decisions",
        headers={"Authorization": f"Bearer {student_key}"},
        json={**_DECISION_BODY, "state": long_text},
    )

    assert response.status_code == 200
    teacher_id = _teacher_of(repo)["id"]
    [log] = repo.list_prompt_logs(teacher_id, klass["id"])
    messages = repo.get_prompt_log(teacher_id, klass["id"], log["id"])["messages"]
    by_role = {message["role"]: message["content"] for message in messages}
    for side in ("user", "assistant"):
        assert len(by_role[side]) == RESPONSE_LOG_MAX_CHARS
        assert by_role[side].endswith(LOG_TRUNCATED_SUFFIX)
