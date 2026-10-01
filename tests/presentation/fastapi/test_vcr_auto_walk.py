import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from fakes import FakeRequestLogger
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.domain.errors import UpstreamServiceError
from src.domain.vcr_auto import VCR_AUTO_MODEL_ID
from src.infrastructure.config import AuthSettings, DatabaseSettings, ProviderSettings, RouterSettings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router

FIRST = "ollama_cloud@kimi-k3:cloud"
SECOND = "openrouter@vendor/second"
FIRST_UPSTREAM = "kimi-k3:cloud"
SECOND_UPSTREAM = "vendor/second"
EXTRA_USAGE = '{"error":"extra usage balance is empty, add extra usage"}'
CREDIT = (
    '{"error":{"message":"Insufficient credits. Add more using '
    'https://openrouter.ai/credits","metadata":{"error_type":"payment_required"}}}'
)


def _provider(name: str, *, cap: int = 4, timeout: float = 30) -> OpenAICompatibleGateway:
    return OpenAICompatibleGateway(
        ProviderSettings(
            name=name,
            base_url=f"https://{name}.test/v1",
            api_key=f"{name}-key",
            max_concurrent_per_key=cap,
            queue_timeout_sec=timeout,
            acquire_delay_ms=0,
            quarantine_ttl_sec=3600,
        )
    )


def _json_response(status: int, body: dict | str) -> MagicMock:
    if isinstance(body, dict):
        text = json.dumps(body)
        json_body = body
    else:
        text = body
        json_body = json.loads(body)
    response = MagicMock()
    response.status_code = status
    response.text = text
    response.json = MagicMock(return_value=json_body)
    return response


def _chat_payload(model: str) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }


class _BytesStream:
    def __init__(self, chunks: list[bytes], *, status_code: int = 200, error: Exception | None = None):
        self.status_code = status_code
        self._chunks = chunks
        self._error = error

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error

    async def aread(self):
        return b"".join(self._chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _install(gateway: OpenAICompatibleGateway, response: MagicMock, stream: _BytesStream | None = None) -> None:
    gateway._client = MagicMock()
    gateway._client.request = AsyncMock(return_value=response)
    gateway._client.stream = MagicMock(return_value=stream or _BytesStream([b""]))


def _document(models: list[dict]) -> list[dict]:
    return [{"name": "VCRouter", "vendor": "customendpoint", "models": models}]


def _model(model_id: str, **flags: bool) -> dict:
    return {"id": model_id, "name": model_id, **flags}


class _Harness:
    def __init__(self, tmp_path, *, cap: int = 4, timeout: float = 30):
        settings = RouterSettings(
            path=str(tmp_path / "router.yaml"),
            public_url="http://testserver",
            database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
            auth=AuthSettings(session_secret="test-secret"),
        )
        self.repo = SqliteRouterRepository(settings.database.path, settings)
        self.ollama = _provider("ollama_cloud", cap=cap, timeout=timeout)
        self.openrouter = _provider("openrouter", cap=cap, timeout=timeout)
        self.gateway = RoutingGateway({"ollama_cloud": self.ollama, "openrouter": self.openrouter})
        self.api = ApiUseCase(
            gateway=self.gateway,
            api_key_repo=self.repo,
            logger=FakeRequestLogger(),
        )
        auth = AuthUseCase(api_key_repo=self.repo)
        app = FastAPI()
        register_error_handlers(app)
        app.add_middleware(ApiKeyMiddleware, auth_use_case=auth)
        app.include_router(create_api_router(self.api, auth_use_case=auth))
        self.app = app
        teacher = self.repo.upsert_google_user("teacher@school.edu", "Teacher")
        self.repo.update_user(teacher["id"], roles=["teacher"])
        self.teacher = teacher
        self.klass = self.repo.create_class(teacher["id"], "AI 素養", None, 2)
        self.session = self.repo.create_class_session(self.klass["id"], teacher["id"], "第一堂")
        student = self.repo.upsert_google_user("student@school.edu", "Student")
        self.student_key = self.repo.redeem_invite(self.session["invite_code"], student["id"])["api_key"]
        self.headers = {"Authorization": f"Bearer {self.student_key}"}
        _install(self.ollama, _json_response(200, _chat_payload(FIRST_UPSTREAM)))
        _install(self.openrouter, _json_response(200, _chat_payload(SECOND_UPSTREAM)))

    def set_models(self, models: list[dict]) -> None:
        self.repo.update_class_session(
            self.klass["id"],
            self.session["id"],
            session_chat_language_models=_document(models),
        )

    def logs(self) -> list[dict]:
        return self.repo.list_prompt_logs(
            self.teacher["id"],
            self.klass["id"],
            session_id=self.session["id"],
            limit=20,
        )

    def auth(self):
        return self.repo.verify_api_key_context(self.student_key)


def _text_shelf() -> list[dict]:
    return [_model(FIRST), _model(SECOND)]


def _sse_models(body: str) -> list[str]:
    found: list[str] = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            continue
        payload = json.loads(raw)
        if isinstance(payload, dict) and isinstance(payload.get("model"), str):
            found.append(payload["model"])
    return found


def _chat_chunk(model: str) -> bytes:
    payload = {
        "id": "c",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hi"}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


@pytest.fixture
def harness(tmp_path):
    return _Harness(tmp_path)


def test_chat_vcr_auto_uses_the_first_text_model_and_hides_it(harness: _Harness):
    harness.set_models(_text_shelf())
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert harness.ollama._client.request.await_count == 1
    assert harness.ollama._client.request.await_args.kwargs["json"]["model"] == FIRST_UPSTREAM
    assert harness.openrouter._client.request.await_count == 0
    assert [log["model"] for log in harness.logs()] == [FIRST]


def test_responses_vcr_auto_uses_document_order_and_stays_vcr_auto(harness: _Harness):
    harness.set_models([_model(SECOND), _model(FIRST)])
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/responses",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "input": "hi"},
    )
    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert harness.openrouter._client.request.await_count == 1
    assert harness.openrouter._client.request.await_args.kwargs["json"]["model"] == SECOND_UPSTREAM
    assert harness.ollama._client.request.await_count == 0
    assert [log["model"] for log in harness.logs()] == [SECOND]


@pytest.mark.parametrize("body", [EXTRA_USAGE, CREDIT])
def test_chat_vcr_auto_walks_after_key_failover_exhaustion(harness: _Harness, body: str):
    harness.set_models(_text_shelf())
    harness.ollama._client.request = AsyncMock(return_value=_json_response(402, body))
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert harness.ollama._client.request.await_count == 1
    assert harness.openrouter._client.request.await_count == 1
    assert harness.openrouter._client.request.await_args.kwargs["json"]["model"] == SECOND_UPSTREAM
    assert [log["model"] for log in harness.logs()] == [SECOND]


def test_chat_vcr_auto_moves_on_when_the_pool_has_no_selectable_key(harness: _Harness):
    harness.set_models(_text_shelf())
    harness.ollama._pool.quarantine(0, "extra usage balance is empty, add extra usage")
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert harness.ollama._client.request.await_count == 0
    assert harness.openrouter._client.request.await_args.kwargs["json"]["model"] == SECOND_UPSTREAM
    assert [log["model"] for log in harness.logs()] == [SECOND]


def test_chat_vcr_auto_does_not_walk_on_other_upstream_errors(harness: _Harness):
    harness.set_models(_text_shelf())
    harness.ollama._client.request = AsyncMock(
        return_value=_json_response(500, {"error": {"message": "boom"}})
    )
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 500
    assert harness.openrouter._client.request.await_count == 0
    assert harness.logs() == []


def test_empty_text_shelf_refuses_vcr_auto_before_upstream(harness: _Harness):
    harness.set_models([])
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"
    assert harness.ollama._client.request.await_count == 0
    assert harness.logs() == []


def test_named_model_on_the_shelf_keeps_today_rules(harness: _Harness):
    harness.set_models(_text_shelf())
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": FIRST, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["model"] == FIRST_UPSTREAM
    assert harness.openrouter._client.request.await_count == 0
    assert [log["model"] for log in harness.logs()] == [FIRST]


def test_named_model_off_the_shelf_is_refused(harness: _Harness):
    harness.set_models([_model(FIRST)])
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": SECOND, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"
    assert harness.ollama._client.request.await_count == 0
    assert harness.openrouter._client.request.await_count == 0


def test_decision_model_is_still_refused_on_chat(harness: _Harness):
    harness.set_models([_model(FIRST), _model(SECOND, decisionShelf=True)])
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": SECOND, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"
    allowed = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert allowed.status_code == 200
    assert harness.openrouter._client.request.await_count == 0
    assert [log["model"] for log in harness.logs()] == [FIRST]


def test_chat_stream_chunks_stay_vcr_auto(harness: _Harness):
    harness.set_models(_text_shelf())
    harness.ollama._client.stream = MagicMock(return_value=_BytesStream([_chat_chunk(FIRST_UPSTREAM), b"data: [DONE]\n\n"]))
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/chat/completions",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    assert response.status_code == 200
    assert set(_sse_models(response.text)) == {VCR_AUTO_MODEL_ID}
    assert harness.openrouter._client.stream.call_count == 0
    assert [log["model"] for log in harness.logs()] == [FIRST]


def test_responses_stream_chunks_stay_vcr_auto(harness: _Harness):
    harness.set_models([_model(SECOND), _model(FIRST)])
    event = {
        "type": "response.completed",
        "response": {"id": "resp_1", "object": "response", "model": SECOND_UPSTREAM, "output": []},
    }
    harness.openrouter._client.stream = MagicMock(
        return_value=_BytesStream([f"data: {json.dumps(event)}\n\n".encode()])
    )
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/responses",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "input": "hi", "stream": True},
    )
    assert response.status_code == 200
    assert VCR_AUTO_MODEL_ID in response.text
    assert SECOND_UPSTREAM not in response.text
    assert [log["model"] for log in harness.logs()] == [SECOND]


def test_image_vcr_auto_uses_only_the_image_shelf_and_keeps_upstream_model(harness: _Harness):
    harness.set_models([_model(FIRST), _model(SECOND, imageShelf=True)])
    image = {"created": 1, "model": "vendor/second", "data": [{"b64_json": "abc"}]}
    harness.openrouter._client.request = AsyncMock(return_value=_json_response(200, image))
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/images",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "prompt": "a robot"},
    )
    assert response.status_code == 200
    assert response.json()["model"] == "vendor/second"
    assert harness.ollama._client.request.await_count == 0
    assert harness.openrouter._client.request.await_args.kwargs["json"]["model"] == SECOND_UPSTREAM
    assert [log["model"] for log in harness.logs()] == [SECOND]


def test_empty_image_shelf_refuses_vcr_auto_before_upstream(harness: _Harness):
    harness.set_models([_model(FIRST)])
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/images",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "prompt": "a robot"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "image_generation_disabled"
    assert harness.ollama._client.request.await_count == 0
    assert harness.openrouter._client.request.await_count == 0


def test_speech_vcr_auto_uses_only_the_speech_shelf(harness: _Harness):
    speech = "openai@gpt-4o-mini-tts"
    harness.gateway.gateways["openai"] = _provider("openai")
    speech_gateway = harness.gateway.gateways["openai"]
    _install(speech_gateway, _json_response(200, {}))
    speech_gateway._client.stream = MagicMock(return_value=_BytesStream([b"\x00\x01"]))
    harness.set_models([_model(FIRST), _model(speech, speechShelf=True)])
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/audio/speech",
        headers=harness.headers,
        json={"model": VCR_AUTO_MODEL_ID, "input": "hello", "voice": "alloy"},
    )
    assert response.status_code == 200
    assert response.content == b"\x00\x01"
    assert harness.ollama._client.stream.call_count == 0
    assert speech_gateway._client.stream.call_args.kwargs["json"]["model"] == "gpt-4o-mini-tts"
    assert [log["model"] for log in harness.logs()] == [speech]


def test_transcription_vcr_auto_uses_only_the_transcription_shelf(harness: _Harness):
    heard = "openai@gpt-4o-mini-transcribe"
    harness.gateway.gateways["openai"] = _provider("openai")
    heard_gateway = harness.gateway.gateways["openai"]
    _install(heard_gateway, _json_response(200, {"text": "hello"}))
    harness.set_models([_model(FIRST), _model(heard, speechTranscriptionShelf=True)])
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/audio/transcriptions",
        headers=harness.headers,
        data={"model": VCR_AUTO_MODEL_ID},
        files={"file": ("clip.wav", b"RIFFaudio", "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "hello"
    assert harness.ollama._client.request.await_count == 0
    assert heard_gateway._client.request.await_args.kwargs["data"]["model"] == "gpt-4o-mini-transcribe"
    assert [log["model"] for log in harness.logs()] == [heard]


def test_decision_vcr_auto_keeps_the_upstream_model_string(harness: _Harness):
    decision = "openrouter@typesafe/jev-1.13"
    harness.set_models([_model(FIRST), _model(decision, decisionShelf=True)])
    upstream = {
        "id": "gen-1",
        "model": "typesafe/jev-1.13",
        "answers": {"urgent": "no"},
        "usage": {"input_tokens": 1, "output_tokens": 1, "cost": 0},
    }
    harness.openrouter._client.request = AsyncMock(return_value=_json_response(200, upstream))
    from fastapi.testclient import TestClient

    client = TestClient(harness.app)
    response = client.post(
        "/v1/decisions",
        headers=harness.headers,
        json={
            "model": VCR_AUTO_MODEL_ID,
            "state": "付款失敗三天了",
            "questions": {"urgent": {"type": "noul", "instructions": "急迫嗎？"}},
        },
    )
    assert response.status_code == 200
    assert response.json()["model"] == "typesafe/jev-1.13"
    assert harness.ollama._client.request.await_count == 0
    assert harness.openrouter._client.request.await_args.kwargs["json"]["model"] == "typesafe/jev-1.13"
    assert harness.logs() == []


@pytest.mark.asyncio
async def test_full_pool_moves_to_the_next_provider_without_queueing(tmp_path):
    harness = _Harness(tmp_path, cap=1, timeout=30)
    harness.set_models(_text_shelf())
    held = await harness.ollama._pool.acquire()
    try:
        transport = httpx.ASGITransport(app=harness.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post(
                "/v1/chat/completions",
                headers=harness.headers,
                json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
                timeout=1,
            )
    finally:
        await harness.ollama._pool.release(held)
    assert response.status_code == 200
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert harness.ollama._client.request.await_count == 0
    assert harness.openrouter._client.request.await_args.kwargs["json"]["model"] == SECOND_UPSTREAM
    assert [log["model"] for log in harness.logs()] == [SECOND]


@pytest.mark.asyncio
async def test_later_model_on_the_same_provider_does_not_add_a_slot(tmp_path):
    harness = _Harness(tmp_path, cap=1, timeout=0.05)
    harness.set_models([_model("ollama_cloud@first:cloud"), _model("ollama_cloud@second:cloud")])
    held = await harness.ollama._pool.acquire()
    try:
        transport = httpx.ASGITransport(app=harness.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post(
                "/v1/chat/completions",
                headers=harness.headers,
                json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
                timeout=2,
            )
    finally:
        await harness.ollama._pool.release(held)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_busy"
    assert response.json()["model"] == VCR_AUTO_MODEL_ID
    assert harness.ollama._client.request.await_count == 0
    assert harness.logs() == []


@pytest.mark.asyncio
async def test_every_full_pool_waits_then_returns_busy_without_a_prompt_log(tmp_path):
    harness = _Harness(tmp_path, cap=1, timeout=0.05)
    harness.set_models(_text_shelf())
    held_ollama = await harness.ollama._pool.acquire()
    held_openrouter = await harness.openrouter._pool.acquire()
    try:
        transport = httpx.ASGITransport(app=harness.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post(
                "/v1/chat/completions",
                headers=harness.headers,
                json={"model": VCR_AUTO_MODEL_ID, "messages": [{"role": "user", "content": "hi"}]},
                timeout=2,
            )
    finally:
        await harness.ollama._pool.release(held_ollama)
        await harness.openrouter._pool.release(held_openrouter)
    assert response.status_code == 503
    body = response.json()
    assert body["model"] == VCR_AUTO_MODEL_ID
    assert body["error"]["code"] == "upstream_busy"
    assert "queue timeout" in body["error"]["message"]
    assert harness.ollama._client.request.await_count == 0
    assert harness.openrouter._client.request.await_count == 0
    assert harness.logs() == []


@pytest.mark.asyncio
async def test_busy_chat_stream_keeps_vcr_auto(tmp_path):
    harness = _Harness(tmp_path, cap=1, timeout=0.05)
    harness.set_models(_text_shelf())
    held_ollama = await harness.ollama._pool.acquire()
    held_openrouter = await harness.openrouter._pool.acquire()
    try:
        transport = httpx.ASGITransport(app=harness.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post(
                "/v1/chat/completions",
                headers=harness.headers,
                json={
                    "model": VCR_AUTO_MODEL_ID,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
                timeout=2,
            )
    finally:
        await harness.ollama._pool.release(held_ollama)
        await harness.openrouter._pool.release(held_openrouter)
    assert response.status_code == 200
    assert set(_sse_models(response.text)) == {VCR_AUTO_MODEL_ID}
    assert "busy" in response.text.lower()
    assert harness.logs() == []


@pytest.mark.asyncio
async def test_stream_that_already_produced_output_does_not_switch_model(tmp_path):
    harness = _Harness(tmp_path)
    harness.set_models(_text_shelf())
    harness.ollama._client.stream = MagicMock(
        return_value=_BytesStream(
            [_chat_chunk(FIRST_UPSTREAM)],
            error=UpstreamServiceError(status_code=402, backend="ollama_cloud", body=EXTRA_USAGE),
        )
    )
    chunks: list[bytes] = []
    with pytest.raises(UpstreamServiceError):
        async for chunk in harness.api.chat_stream(
            _chat_request(),
            harness.student_key,
            None,
            harness.auth(),
        ):
            chunks.append(chunk)
    assert chunks
    assert b"vcr-auto" in b"".join(chunks)
    assert harness.openrouter._client.stream.call_count == 0
    assert harness.logs() == []


@pytest.mark.asyncio
async def test_realtime_vcr_auto_uses_the_transcription_shelf_in_order(tmp_path):
    harness = _Harness(tmp_path, cap=1, timeout=30)
    first = "ollama_cloud@whisper-1"
    second = "openrouter@openai/whisper-2"
    harness.set_models([_model(FIRST), _model(first, speechTranscriptionShelf=True), _model(second, speechTranscriptionShelf=True)])
    held = await harness.ollama._pool.acquire()
    try:
        target, release, model_id = await harness.api.open_realtime(VCR_AUTO_MODEL_ID, harness.auth())
    finally:
        await harness.ollama._pool.release(held)
    assert model_id == second
    assert target.upstream_model == "openai/whisper-2"
    assert target.provider_name == "openrouter"
    assert harness.openrouter._pool.in_flight_snapshot() == [1]
    await release()
    assert harness.openrouter._pool.in_flight_snapshot() == [0]


def _chat_request():
    from src.domain.entities.chat import ChatCompletionRequest, ChatMessage

    return ChatCompletionRequest(
        model=VCR_AUTO_MODEL_ID,
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
