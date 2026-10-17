"""The vcr-auto Selector beyond a sitting (#67, ADR-0037).

Personal API Keys select from the holder's Router Model Template; a new Class Session
copies the template's Auto Tiers and selector shelf; a selector-only Model ID is not a
decision model.
"""

import pytest
from fastapi.testclient import TestClient

from test_vcr_auto_selector import (
    LIGHT,
    SELECTOR,
    STANDARD,
    STRONG,
    _decision,
    _selector_document,
    _Upstream,
)
from test_vcr_auto_walk import CREDIT, _Harness, _json_response, _model
from src.domain.vcr_auto import VCR_AUTO_MODEL_ID


def _personal_chat(harness: _Harness, key: str):
    return TestClient(harness.app).post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "幫我修這個 bug"}]},
    )


def test_personal_api_key_vcr_auto_walks_the_tier_its_template_selector_picks(tmp_path):
    harness = _Harness(tmp_path)
    harness.repo.save_router_model_template(harness.teacher["id"], _selector_document())
    personal = harness.repo.issue_long_lived_key(harness.teacher["id"])
    upstream = _Upstream(
        harness,
        _json_response(200, _decision({"輕量": 0.05, "一般": 0.9, "困難": 0.05})),
        chat_replies={"standard:cloud": _json_response(402, CREDIT)},
    )

    response = _personal_chat(harness, personal)

    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert len(upstream.selector_bodies) == 1
    assert upstream.selector_bodies[0]["model"] == "typesafe/jev-1.14"
    assert upstream.chat == ["standard:cloud", "vendor/strong"]


def test_personal_api_key_prompt_log_keeps_the_tier_its_template_selector_picks(tmp_path):
    harness = _Harness(tmp_path)
    harness.repo.save_router_model_template(harness.teacher["id"], _selector_document())
    personal = harness.repo.issue_long_lived_key(harness.teacher["id"])
    _Upstream(harness, _json_response(200, _decision({"輕量": 0.05, "一般": 0.9, "困難": 0.05})))

    assert _personal_chat(harness, personal).status_code == 200

    with harness.repo._connect() as conn:
        rows = conn.execute(
            harness.repo._sql(
                "SELECT model, tier_name, tier_confidence FROM prompt_logs"
                " WHERE user_id = ? AND session_id IS NULL"
            ),
            (harness.teacher["id"],),
        ).fetchall()
    assert [tuple(row) for row in rows] == [(STANDARD, "一般", 0.9)]


def test_personal_api_key_with_an_empty_template_selector_shelf_keeps_document_order(tmp_path):
    harness = _Harness(tmp_path)
    harness.repo.save_router_model_template(harness.teacher["id"], _selector_document(selector=[]))
    personal = harness.repo.issue_long_lived_key(harness.teacher["id"])
    upstream = _Upstream(
        harness,
        _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})),
        chat_replies={"vendor/light": _json_response(402, CREDIT)},
    )

    response = _personal_chat(harness, personal)

    assert response.status_code == 200
    assert upstream.selector_bodies == []
    assert upstream.chat == ["vendor/light", "standard:cloud"]


def _router_only(document: list[dict]) -> dict:
    """The Auto Tiers, selector shelf, and each model's tier of a saved document."""
    provider = document[0]
    return {
        "autoTiers": provider.get("autoTiers"),
        "selectorShelf": provider.get("selectorShelf"),
        "tiers": {model["id"]: model.get("autoTier") for model in provider["models"]},
    }


def test_new_class_session_copies_the_template_tiers_and_selector_shelf_independently(tmp_path):
    from test_extension_portal import _client, _portal_cookie

    client, repo, _ = _client(tmp_path)
    owner = repo.upsert_google_user("owner@school.edu", "Owner")
    cookies = _portal_cookie(repo, owner["id"])
    saved = client.put(
        "/teacher/router-model-template",
        cookies=cookies,
        json={"router_model_template": _selector_document()},
    )
    assert saved.status_code == 200
    template_view = _router_only(saved.json())
    assert template_view == {
        "autoTiers": [
            {"id": "t-light", "name": "輕量", "description": "語法小問題"},
            {"id": "t-standard", "name": "一般", "description": "單一檔案的功能"},
            {"id": "t-strong", "name": "困難", "description": "跨檔案除錯"},
        ],
        "selectorShelf": [SELECTOR],
        "tiers": {
            LIGHT: "t-light",
            STANDARD: "t-standard",
            STRONG: "t-strong",
            "openrouter@vendor/strong-too": "t-strong",
        },
    }

    klass = repo.create_class(owner["id"], "Demo", None, 2)
    created = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "Week 1"},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    assert _router_only(created.json()["session_chat_language_models"]) == template_view

    changed_template = _selector_document(
        tiers=[{"id": "t-light", "name": "輕量", "description": "只改範本"}],
        selector=["openrouter@typesafe/template-later"],
    )
    assert client.put(
        "/teacher/router-model-template",
        cookies=cookies,
        json={"router_model_template": changed_template},
    ).status_code == 200
    sitting = client.get(f"/teacher/classes/{klass['id']}/sessions/{session_id}", cookies=cookies)
    assert _router_only(sitting.json()["session_chat_language_models"]) == template_view

    changed_sitting = _selector_document(
        tiers=[{"id": "t-strong", "name": "困難", "description": "只改課堂"}],
        selector=["openrouter@typesafe/sitting-later"],
    )
    patched = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session_id}",
        cookies=cookies,
        json={"session_chat_language_models": changed_sitting},
    )
    assert patched.status_code == 200
    template = client.get("/teacher/router-model-template", cookies=cookies).json()
    assert template[0]["autoTiers"] == [{"id": "t-light", "name": "輕量", "description": "只改範本"}]
    assert template[0]["selectorShelf"] == ["openrouter@typesafe/template-later"]


_DECISION_BODY = {
    "model": SELECTOR,
    "state": "付款失敗三天了",
    "questions": {"urgent": {"type": "noul", "instructions": "這則訊息急迫嗎？"}},
}


def _both_shelves_document() -> list[dict]:
    """The selector Model ID also sits on the decision shelf."""
    document = _selector_document()
    document[0]["models"].append(_model(SELECTOR, decisionShelf=True))
    return document


def _set_choice(harness: _Harness, choice: str | None) -> None:
    with harness.repo._connect() as conn:
        conn.execute(
            harness.repo._sql("UPDATE class_sessions SET classroom_model_choice = ? WHERE id = ?"),
            (choice, harness.session["id"]),
        )


def _decide(harness: _Harness, headers: dict):
    return TestClient(harness.app).post("/v1/decisions", headers=headers, json=_DECISION_BODY)


def _decision_list(harness: _Harness, headers: dict):
    return TestClient(harness.app).get("/v1/decisions/models", headers=headers)


@pytest.mark.parametrize("choice", [None, "picked"])
def test_classroom_key_cannot_decide_with_a_selector_only_model_id(tmp_path, choice):
    harness = _Harness(tmp_path)
    harness.set_models([])
    _set_document_raw(harness, _selector_document())
    _set_choice(harness, choice)
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 1.0, "一般": 0.0, "困難": 0.0})))

    refused = _decide(harness, harness.headers)
    listed = _decision_list(harness, harness.headers)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "decision_disabled"
    assert SELECTOR not in listed.text
    assert upstream.selector_bodies == []
    assert harness.repo.get_decision_model_ids(harness.session["id"]) == []


def test_personal_key_cannot_decide_with_a_selector_only_model_id(tmp_path):
    harness = _Harness(tmp_path)
    harness.repo.save_router_model_template(harness.teacher["id"], _selector_document())
    headers = {"Authorization": f"Bearer {harness.repo.issue_long_lived_key(harness.teacher['id'])}"}
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 1.0, "一般": 0.0, "困難": 0.0})))

    refused = _decide(harness, headers)
    listed = _decision_list(harness, headers)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "decision_disabled"
    assert SELECTOR not in listed.text
    assert upstream.selector_bodies == []


def test_classroom_key_decides_with_and_is_selected_by_a_model_id_on_both_shelves(tmp_path):
    harness = _Harness(tmp_path)
    _set_document_raw(harness, _both_shelves_document())
    _set_choice(harness, "picked")
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 1.0, "困難": 0.0})))

    decided = _decide(harness, harness.headers)
    listed = _decision_list(harness, harness.headers)

    assert decided.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [SELECTOR]

    _set_choice(harness, "automatic")
    upstream.selector_bodies.clear()
    chat = TestClient(harness.app).post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "寫一個函式"}]},
    )

    assert chat.status_code == 200
    assert [body["model"] for body in upstream.selector_bodies] == ["typesafe/jev-1.14"]
    assert upstream.chat == ["standard:cloud"]


def test_personal_key_decides_with_and_is_selected_by_a_model_id_on_both_shelves(tmp_path):
    harness = _Harness(tmp_path)
    harness.repo.save_router_model_template(harness.teacher["id"], _both_shelves_document())
    key = harness.repo.issue_long_lived_key(harness.teacher["id"])
    headers = {"Authorization": f"Bearer {key}"}
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 1.0, "困難": 0.0})))

    decided = _decide(harness, headers)

    assert decided.status_code == 200
    upstream.selector_bodies.clear()
    chat = _personal_chat(harness, key)

    assert chat.status_code == 200
    assert [body["model"] for body in upstream.selector_bodies] == ["typesafe/jev-1.14"]
    assert upstream.chat == ["standard:cloud"]


def _set_document_raw(harness: _Harness, document: list[dict]) -> None:
    harness.repo.update_class_session(
        harness.klass["id"],
        harness.session["id"],
        session_chat_language_models=document,
    )
