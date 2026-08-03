import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from fakes import FakeLLMGateway, FakeRequestLogger
from infrastructure.test_routing_gateway import FakeGateway
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import (
    AuthSettings,
    CAPABILITY_AUDIO_TRANSCRIPTION,
    DatabaseSettings,
    ProviderSettings,
    RouterSettings,
)
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
import asyncio


class FakeUpstreamSocket:
    def __init__(self):
        self.sent: list[str | bytes] = []
        self._outbound: asyncio.Queue[str | bytes | None] = asyncio.Queue()
        self.closed = False
        self.url = ""
        self.headers: dict[str, str] = {}

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._outbound.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True
        await self._outbound.put(None)


def _client_with_upstream(fake_repo, fake_gateway, fake_logger):
    upstream = FakeUpstreamSocket()

    async def connect(url: str, headers: dict[str, str]):
        upstream.url = url
        upstream.headers = headers
        return upstream

    auth_use_case = AuthUseCase(api_key_repo=fake_repo)
    api_use_case = ApiUseCase(gateway=fake_gateway, api_key_repo=fake_repo, logger=fake_logger)
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(
        create_api_router(api_use_case, auth_use_case=auth_use_case, realtime_connect=connect)
    )
    return TestClient(app), upstream


def _wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for condition")


def test_realtime_rejects_invalid_api_key(fake_repo, fake_gateway, fake_logger):
    client, _upstream = _client_with_upstream(fake_repo, fake_gateway, fake_logger)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/v1/realtime?model=openai@gpt-live-transcribe"):
            pass
    assert exc.value.code == 1008


def test_realtime_proxies_text_and_rewrites_model(fake_repo, fake_gateway, fake_logger):
    client, upstream = _client_with_upstream(fake_repo, fake_gateway, fake_logger)
    with client.websocket_connect(
        "/v1/realtime?model=openai@gpt-live-transcribe",
        headers={"Authorization": "Bearer valid-key"},
    ) as ws:
        ws.send_text(
            '{"type":"session.update","session":{"audio":{"input":{"transcription":'
            '{"model":"openai@gpt-live-transcribe"}}}}}'
        )
        _wait_for(lambda: bool(upstream.sent))
        assert "openai@" not in upstream.sent[0]
        assert "gpt-live-transcribe" in upstream.sent[0]
        assert upstream.url.endswith("/v1/realtime?model=gpt-live-transcribe")
        assert upstream.headers["Authorization"] == "Bearer sk-test"


def test_realtime_rejects_unsupported_provider(fake_repo, fake_logger):
    ollama = FakeGateway("ollama_cloud")
    openrouter = FakeGateway("openrouter")
    openai = FakeGateway("openai", (CAPABILITY_AUDIO_TRANSCRIPTION,))
    openai.provider = ProviderSettings(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-live",
        capabilities=(CAPABILITY_AUDIO_TRANSCRIPTION,),
    )
    routing = RoutingGateway({"ollama_cloud": ollama, "openrouter": openrouter, "openai": openai})
    client, _upstream = _client_with_upstream(fake_repo, routing, FakeRequestLogger())
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/v1/realtime?model=openrouter@gpt-live-transcribe",
            headers={"Authorization": "Bearer valid-key"},
        ):
            pass
    assert exc.value.code == 1008


def test_session_speech_transcription_toggle_blocks_realtime(tmp_path):
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    gateway = FakeLLMGateway()
    logger = FakeRequestLogger()
    upstream = FakeUpstreamSocket()

    async def connect(url: str, headers: dict[str, str]):
        upstream.url = url
        upstream.headers = headers
        return upstream

    auth_use_case = AuthUseCase(api_key_repo=repo)
    api_use_case = ApiUseCase(gateway=gateway, api_key_repo=repo, logger=logger)
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(
        create_api_router(api_use_case, auth_use_case=auth_use_case, realtime_connect=connect)
    )
    client = TestClient(app)

    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    student_key = redeem["api_key"]

    assert repo.is_speech_transcription_enabled(session["id"]) is False
    with pytest.raises(WebSocketDisconnect) as blocked:
        with client.websocket_connect(
            "/v1/realtime?model=openai@gpt-live-transcribe",
            headers={"Authorization": f"Bearer {student_key}"},
        ):
            pass
    assert blocked.value.code == 1008

    repo.update_class_session(klass["id"], session["id"], speech_transcription_enabled=True)
    with client.websocket_connect(
        "/v1/realtime?model=openai@gpt-live-transcribe",
        headers={"Authorization": f"Bearer {student_key}"},
    ) as ws:
        ws.send_text('{"type":"input_audio_buffer.append","audio":"AA=="}')
        _wait_for(lambda: bool(upstream.sent))
        assert upstream.sent[0] == '{"type":"input_audio_buffer.append","audio":"AA=="}'
