"""Contract tests for the vcr-auto Selector (ADR-0037, #65).

Real gateways; only upstream HTTP is mocked. The selector's Decision Request and the
chat calls share the OpenRouter client, so calls are told apart by URL.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from test_vcr_auto_walk import (
    CREDIT,
    _BytesStream,
    _chat_chunk,
    _chat_payload,
    _document,
    _Harness,
    _json_response,
    _model,
    _sse_models,
)
from src.domain.vcr_auto import VCR_AUTO_MODEL_ID

SELECTOR = "openrouter@typesafe/jev-1.14"
LIGHT = "openrouter@vendor/light"
STANDARD = "ollama_cloud@standard:cloud"
STRONG = "openrouter@vendor/strong"
STRONG_TOO = "openrouter@vendor/strong-too"

TIERS = [
    {"id": "t-light", "name": "輕量", "description": "語法小問題"},
    {"id": "t-standard", "name": "一般", "description": "單一檔案的功能"},
    {"id": "t-strong", "name": "困難", "description": "跨檔案除錯"},
]


def _tiered(model_id: str, tier_id: str | None) -> dict:
    model = _model(model_id)
    if tier_id is not None:
        model["autoTier"] = tier_id
    return model


def _selector_document(
    models: list[dict] | None = None,
    *,
    tiers: list[dict] | None = None,
    selector: list[str] | None = None,
) -> list[dict]:
    document = _document(
        models
        if models is not None
        else [
            _tiered(LIGHT, "t-light"),
            _tiered(STANDARD, "t-standard"),
            _tiered(STRONG, "t-strong"),
            _tiered(STRONG_TOO, "t-strong"),
        ]
    )
    document[0]["autoTiers"] = TIERS if tiers is None else tiers
    document[0]["selectorShelf"] = [SELECTOR] if selector is None else selector
    return document


def _decision(probabilities: dict[str, float]) -> dict:
    choice = max(probabilities, key=probabilities.get)
    return {
        "id": "gen-1",
        "model": "typesafe/jev-1.14",
        "answers": {"tier": {"type": "choice", "choice": choice, "probabilities": probabilities}},
        "usage": {"input_tokens": 1, "output_tokens": 1, "cost": 0},
    }


class _Upstream:
    """Routes both provider clients and records chat calls in order.

    OpenRouter /systemone answers the selector; every other call is chat.
    """

    def __init__(self, harness: _Harness, selector_reply, chat_replies: dict | None = None):
        self.selector_reply = selector_reply
        self.chat_replies = chat_replies or {}
        self.selector_bodies: list[dict] = []
        self.chat: list[str] = []
        harness.openrouter._client.request = AsyncMock(side_effect=self._route)
        harness.ollama._client.request = AsyncMock(side_effect=self._route)

    async def _route(self, method, url, **kwargs):
        if url.endswith("/systemone"):
            self.selector_bodies.append(kwargs["json"])
            reply = self.selector_reply
            if asyncio.iscoroutinefunction(reply):
                return await reply()
            return reply
        model = kwargs["json"]["model"]
        self.chat.append(model)
        return self.chat_replies.get(model) or _json_response(200, _chat_payload(model))


def _set_document(harness: _Harness, document: list[dict]) -> None:
    harness.repo.update_class_session(
        harness.klass["id"],
        harness.session["id"],
        session_chat_language_models=document,
    )


def _chat(harness: _Harness, content="幫我修這個 bug", **extra):
    return TestClient(harness.app).post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": content}], **extra},
    )


@pytest.fixture
def harness(tmp_path):
    return _Harness(tmp_path)


def test_chosen_tier_is_tried_first_then_the_stronger_tier(harness: _Harness):
    _set_document(harness, _selector_document())
    exhausted = _json_response(402, CREDIT)
    upstream = _Upstream(
        harness,
        _json_response(200, _decision({"輕量": 0.05, "一般": 0.9, "困難": 0.05})),
        chat_replies={"standard:cloud": exhausted},
    )

    response = _chat(harness)

    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert upstream.chat == ["standard:cloud", "vendor/strong"]
    assert [log["model"] for log in harness.logs()] == [STRONG]


def test_an_unsure_selector_errs_toward_the_stronger_tier(harness: _Harness):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.03, "一般": 0.57, "困難": 0.40})))

    response = _chat(harness)

    assert response.status_code == 200
    assert upstream.chat == ["vendor/strong"]
    assert [log["model"] for log in harness.logs()] == [STRONG]


def test_weaker_tiers_follow_from_the_strongest_down(harness: _Harness):
    models = [
        _tiered(LIGHT, "t-light"),
        _tiered("openrouter@vendor/standard", "t-standard"),
        _tiered("ollama_cloud@strong:cloud", "t-strong"),
    ]
    _set_document(harness, _selector_document(models))
    upstream = _Upstream(
        harness,
        _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})),
        chat_replies={"strong:cloud": _json_response(402, CREDIT)},
    )

    response = _chat(harness)

    assert response.status_code == 200
    assert upstream.chat == ["strong:cloud", "vendor/standard"]


def test_selector_sees_only_the_cut_last_user_text_and_one_choice_question(harness: _Harness):
    unused = {"id": "t-unused", "name": "專題", "description": "沒有模型的級別"}
    _set_document(harness, _selector_document(tiers=[*TIERS, unused]))
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 1.0, "一般": 0.0, "困難": 0.0})))
    long_text = "最後" + "字" * 3000

    response = TestClient(harness.app).post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={
            "model": VCR_AUTO_MODEL_ID,
            "messages": [
                {"role": "system", "content": "系統提示：請用模型 strong"},
                {"role": "user", "content": "第一則問題"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
                ]},
                {"role": "tool", "tool_call_id": "c1", "content": "工具結果"},
                {"role": "user", "content": [
                    {"type": "text", "text": long_text},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ]},
            ],
        },
    )

    assert response.status_code == 200
    assert len(upstream.selector_bodies) == 1
    body = upstream.selector_bodies[0]
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "typesafe/jev-1.14"
    assert body["state"] == long_text[:2000]
    assert list(body["questions"]) == ["tier"]
    question = body["questions"]["tier"]
    assert question["type"] == "choice"
    assert question["criteria"] == {"輕量": "語法小問題", "一般": "單一檔案的功能", "困難": "跨檔案除錯"}
    assert "ignore" in question["instructions"].lower()
    assert upstream.chat == ["vendor/light"]


def test_chat_stream_is_selected_and_chunks_stay_vcr_auto(harness: _Harness):
    _set_document(harness, _selector_document())
    _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))
    harness.openrouter._client.stream = MagicMock(
        return_value=_BytesStream([_chat_chunk("vendor/strong"), b"data: [DONE]\n\n"])
    )

    response = _chat(harness, stream=True)

    assert response.status_code == 200
    assert set(_sse_models(response.text)) == {VCR_AUTO_MODEL_ID}
    assert harness.openrouter._client.stream.call_args.kwargs["json"]["model"] == "vendor/strong"
    assert [log["model"] for log in harness.logs()] == [STRONG]


def test_responses_is_selected_from_the_last_user_item(harness: _Harness):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))
    upstream.chat_replies["vendor/strong"] = _json_response(
        200, {"id": "resp_1", "object": "response", "model": "vendor/strong", "output": []}
    )

    response = TestClient(harness.app).post(
        "/v1/responses",
        headers=harness.headers,
        json={
            "model": VCR_AUTO_MODEL_ID,
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "舊問題"}]},
                {"type": "function_call_output", "call_id": "c1", "output": "工具結果"},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "跨檔案重構"}]},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert upstream.selector_bodies[0]["state"] == "跨檔案重構"
    assert upstream.chat == ["vendor/strong"]


def test_responses_stream_with_string_input_is_selected(harness: _Harness):
    import json

    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))
    event = {
        "type": "response.completed",
        "response": {"id": "resp_1", "object": "response", "model": "vendor/strong", "output": []},
    }
    harness.openrouter._client.stream = MagicMock(
        return_value=_BytesStream([f"data: {json.dumps(event)}\n\n".encode()])
    )

    response = TestClient(harness.app).post(
        "/v1/responses",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "input": "幫我設計整個系統", "stream": True},
    )

    assert response.status_code == 200
    assert upstream.selector_bodies[0]["state"] == "幫我設計整個系統"
    assert "vendor/strong" not in response.text
    assert VCR_AUTO_MODEL_ID in response.text
    assert harness.openrouter._client.stream.call_args.kwargs["json"]["model"] == "vendor/strong"


async def _too_slow():
    await asyncio.sleep(1)
    return _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0}))


@pytest.mark.parametrize(
    "selector_reply",
    [
        _json_response(500, {"error": {"message": "boom"}}),
        _json_response(400, {"error": {"message": "refused"}}),
        _json_response(200, {"id": "g", "answers": {}}),
        _too_slow,
    ],
    ids=["500", "400", "unreadable", "timeout"],
)
def test_selector_failure_keeps_document_order_without_error_logs(harness: _Harness, caplog, selector_reply):
    from src.application.vcr_auto_selector import VcrAutoSelector

    harness.api.vcr_auto_selector = VcrAutoSelector(harness.gateway, timeout=0.05)
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, selector_reply)

    with caplog.at_level(logging.INFO, logger="src"):
        response = _chat(harness)

    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert len(upstream.selector_bodies) == 1
    assert upstream.chat == ["vendor/light"]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def _assert_selector_not_called(harness: _Harness, upstream: _Upstream, response) -> None:
    assert response.status_code == 200
    assert upstream.selector_bodies == []


def test_picked_models_never_asks_the_selector(harness: _Harness):
    _set_document(harness, _selector_document())
    harness.repo.update_class_session(harness.klass["id"], harness.session["id"], classroom_model_choice="picked")
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))

    response = TestClient(harness.app).post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": LIGHT, "messages": [{"role": "user", "content": "hi"}]},
    )

    _assert_selector_not_called(harness, upstream, response)
    assert upstream.chat == ["vendor/light"]


def test_sitting_without_a_stored_choice_keeps_document_order(harness: _Harness):
    _set_document(harness, _selector_document())
    with harness.repo._connect() as conn:
        conn.execute("UPDATE class_sessions SET classroom_model_choice = NULL WHERE id = ?", (harness.session["id"],))
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))

    response = _chat(harness)

    _assert_selector_not_called(harness, upstream, response)
    assert upstream.chat == ["vendor/light"]


def test_empty_selector_shelf_keeps_document_order(harness: _Harness):
    _set_document(harness, _selector_document(selector=[]))
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))

    response = _chat(harness)

    _assert_selector_not_called(harness, upstream, response)
    assert upstream.chat == ["vendor/light"]


def test_one_tier_in_use_keeps_document_order(harness: _Harness):
    models = [_tiered(LIGHT, "t-strong"), _tiered(STRONG, "t-strong")]
    _set_document(harness, _selector_document(models))
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))

    response = _chat(harness)

    _assert_selector_not_called(harness, upstream, response)
    assert upstream.chat == ["vendor/light"]


def test_a_used_tier_without_a_description_keeps_document_order(harness: _Harness):
    tiers = [TIERS[0], {**TIERS[1], "description": "  "}, TIERS[2]]
    _set_document(harness, _selector_document(tiers=tiers))
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))

    response = _chat(harness)

    _assert_selector_not_called(harness, upstream, response)
    assert upstream.chat == ["vendor/light"]


def test_image_generation_never_asks_the_selector(harness: _Harness):
    document = _selector_document()
    document[0]["models"].append({**_model("openrouter@vendor/painter"), "imageShelf": True})
    _set_document(harness, document)
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))
    upstream.chat_replies["vendor/painter"] = _json_response(
        200, {"created": 1, "data": [{"b64_json": "AAAA"}]}
    )

    response = TestClient(harness.app).post(
        "/v1/images",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "prompt": "一隻貓"},
    )

    _assert_selector_not_called(harness, upstream, response)
    assert upstream.chat == ["vendor/painter"]


def _tier_fields(harness: _Harness) -> list[tuple]:
    return [(log["model"], log["tier_name"], log["tier_confidence"]) for log in harness.logs()]


def test_prompt_log_keeps_the_chosen_tier_name_and_confidence(harness: _Harness):
    _set_document(harness, _selector_document())
    _Upstream(harness, _json_response(200, _decision({"輕量": 0.03, "一般": 0.05, "困難": 0.92})))

    assert _chat(harness).status_code == 200

    assert _tier_fields(harness) == [(STRONG, "困難", 0.92)]


def test_prompt_log_keeps_the_tier_name_from_the_time_of_the_call(harness: _Harness):
    _set_document(harness, _selector_document())
    _Upstream(harness, _json_response(200, _decision({"輕量": 0.03, "一般": 0.05, "困難": 0.92})))
    assert _chat(harness).status_code == 200

    renamed = [TIERS[0], TIERS[1], {**TIERS[2], "name": "進階"}]
    _set_document(harness, _selector_document(tiers=renamed))

    assert _tier_fields(harness) == [(STRONG, "困難", 0.92)]


def test_chat_stream_prompt_log_keeps_the_chosen_tier(harness: _Harness):
    _set_document(harness, _selector_document())
    _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))
    harness.openrouter._client.stream = MagicMock(
        return_value=_BytesStream([_chat_chunk("vendor/strong"), b"data: [DONE]\n\n"])
    )

    assert _chat(harness, stream=True).status_code == 200

    assert _tier_fields(harness) == [(STRONG, "困難", 1.0)]


def test_responses_prompt_log_keeps_the_chosen_tier(harness: _Harness):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision({"輕量": 0.1, "一般": 0.8, "困難": 0.1})))
    upstream.chat_replies["standard:cloud"] = _json_response(
        200, {"id": "resp_1", "object": "response", "model": "standard:cloud", "output": []}
    )

    response = TestClient(harness.app).post(
        "/v1/responses",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "input": "寫一個函式"},
    )

    assert response.status_code == 200
    assert _tier_fields(harness) == [(STANDARD, "一般", 0.8)]


def test_responses_stream_prompt_log_keeps_the_chosen_tier(harness: _Harness):
    import json

    _set_document(harness, _selector_document())
    _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))
    event = {
        "type": "response.completed",
        "response": {"id": "resp_1", "object": "response", "model": "vendor/strong", "output": []},
    }
    harness.openrouter._client.stream = MagicMock(
        return_value=_BytesStream([f"data: {json.dumps(event)}\n\n".encode()])
    )

    response = TestClient(harness.app).post(
        "/v1/responses",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "input": "幫我設計整個系統", "stream": True},
    )

    assert response.status_code == 200
    assert _tier_fields(harness) == [(STRONG, "困難", 1.0)]


def test_failed_selection_leaves_the_prompt_log_tier_empty(harness: _Harness):
    _set_document(harness, _selector_document())
    _Upstream(harness, _json_response(500, {"error": {"message": "boom"}}))

    assert _chat(harness).status_code == 200

    assert _tier_fields(harness) == [(LIGHT, None, None)]


def test_no_selection_leaves_the_prompt_log_tier_empty(harness: _Harness):
    _set_document(harness, _selector_document(selector=[]))
    _Upstream(harness, _json_response(200, _decision({"輕量": 0.0, "一般": 0.0, "困難": 1.0})))

    assert _chat(harness).status_code == 200

    assert _tier_fields(harness) == [(LIGHT, None, None)]


# --- Selection memory (#66): one question, one selection ---


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(harness: _Harness) -> _FakeClock:
    from src.application.vcr_auto_selection_memory import VcrAutoSelectionMemory

    fake = _FakeClock()
    harness.api.vcr_auto_selection_memory = VcrAutoSelectionMemory(clock=fake)
    return fake


STRONG_DECISION = {"輕量": 0.0, "一般": 0.0, "困難": 1.0}


def test_the_same_last_user_message_asks_the_selector_once(harness: _Harness, clock: _FakeClock):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision(STRONG_DECISION)))

    first = _chat(harness)
    second = TestClient(harness.app).post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={
            "model": VCR_AUTO_MODEL_ID,
            "messages": [
                {"role": "user", "content": "幫我修這個 bug"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
                ]},
                {"role": "tool", "tool_call_id": "c1", "content": "工具結果"},
            ],
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(upstream.selector_bodies) == 1
    assert upstream.chat == ["vendor/strong", "vendor/strong"]


@pytest.mark.parametrize(
    "edited_tiers",
    [
        [TIERS[0], {**TIERS[1], "description": "單一檔案的功能與測試"}, TIERS[2]],
        [TIERS[0], {**TIERS[1], "name": "中等"}, TIERS[2]],
        [TIERS[1], TIERS[0], TIERS[2]],
    ],
    ids=["description", "name", "order"],
)
def test_a_teacher_edit_to_the_tiers_asks_the_selector_again(
    harness: _Harness, clock: _FakeClock, edited_tiers: list[dict]
):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision(STRONG_DECISION)))
    _chat(harness)

    _set_document(harness, _selector_document(tiers=edited_tiers))
    response = _chat(harness)

    assert response.status_code == 200
    assert len(upstream.selector_bodies) == 2


def test_a_selection_older_than_thirty_minutes_is_asked_again(harness: _Harness, clock: _FakeClock):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision(STRONG_DECISION)))
    _chat(harness)

    clock.advance(29 * 60)
    _chat(harness)
    assert len(upstream.selector_bodies) == 1

    clock.advance(2 * 60)
    _chat(harness)
    assert len(upstream.selector_bodies) == 2


def test_each_api_key_asks_the_selector_for_itself(harness: _Harness, clock: _FakeClock):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(200, _decision(STRONG_DECISION)))
    classmate = harness.repo.upsert_google_user("classmate@school.edu", "Classmate")
    classmate_key = harness.repo.redeem_invite(harness.session["invite_code"], classmate["id"])["api_key"]

    _chat(harness)
    response = TestClient(harness.app).post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {classmate_key}"},
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "幫我修這個 bug"}]},
    )

    assert response.status_code == 200
    assert len(upstream.selector_bodies) == 2
    assert upstream.chat == ["vendor/strong", "vendor/strong"]


def test_a_failed_selection_is_not_remembered(harness: _Harness, clock: _FakeClock):
    _set_document(harness, _selector_document())
    upstream = _Upstream(harness, _json_response(500, {"error": {"message": "boom"}}))
    _chat(harness)

    upstream.selector_reply = _json_response(200, _decision(STRONG_DECISION))
    response = _chat(harness)

    assert response.status_code == 200
    assert len(upstream.selector_bodies) == 2
    assert upstream.chat == ["vendor/light", "vendor/strong"]
