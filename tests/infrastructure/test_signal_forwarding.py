"""Production ERROR logs under src are posted once to vans-signals."""

import asyncio
import json
import logging
import threading
import time
from pathlib import Path

import pytest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger
from app import application_lifespan
from src.application.upstream_model_catalog import UpstreamModelCatalogMemory
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, ProviderSettings, RouterSettings
from src.infrastructure.jobs.upstream_model_catalog_job import run_upstream_model_catalog_refresh
from src.infrastructure.logging.signal_forwarder import start_signal_forwarding
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router

ROUTER_SOURCE = "vans-coding-router"


class _RecordingSignals(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _SignalsHandler)
        self.posts: list[dict] = []
        self.hold_response = threading.Event()
        self.release_response = threading.Event()
        self.status = 200


class _SignalsHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        server: _RecordingSignals = self.server  # type: ignore[assignment]
        server.posts.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(raw.decode("utf-8")),
            }
        )
        if server.hold_response.is_set():
            server.release_response.wait(timeout=5)
        self.send_response(server.status)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        return


class _SignalsReceiver:
    def __init__(self) -> None:
        self._server = _RecordingSignals()
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def posts(self) -> list[dict]:
        return self._server.posts

    def fail_with(self, status: int) -> None:
        self._server.status = status

    def hold_responses(self) -> None:
        self._server.hold_response.set()

    def release_responses(self) -> None:
        self._server.release_response.set()

    def close(self) -> None:
        self.release_responses()
        self._server.shutdown()
        self._thread.join(timeout=2)
        self._server.server_close()


def _failure_logs(caplog):
    return [record for record in caplog.records if record.name == "vans_signals_forwarder"]


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def test_one_error_log_under_src_posts_one_signal():
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    try:
        logging.getLogger("src.jobs.catalog").error("upstream openrouter did not update")
        _wait_until(lambda: len(receiver.posts) >= 1)

        assert len(receiver.posts) == 1
        post = receiver.posts[0]
        assert post["path"] == "/signals"
        assert post["authorization"] == "Bearer router-token"
        body = post["body"]
        assert body["logger_name"] == "src.jobs.catalog"
        assert body["level"] == "ERROR"
        assert body["message"] == "upstream openrouter did not update"
        assert body["source"] == ROUTER_SOURCE
        logged_at = datetime.fromisoformat(body["log_time"])
        assert logged_at.tzinfo is not None and logged_at.utcoffset() is not None
        assert "Traceback" not in body["message"]
    finally:
        forwarder.close()
        receiver.close()


def test_posted_json_matches_the_example_keys():
    example = json.loads(
        Path("tests/fixtures/signal_body.example.json").read_text(encoding="utf-8")
    )
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    try:
        logging.getLogger("src.jobs.catalog").error("upstream openrouter did not update")
        _wait_until(lambda: len(receiver.posts) >= 1)

        body = receiver.posts[0]["body"]
        assert body.keys() == example.keys()
        assert len(body) == 5
        assert body["level"] == "ERROR"
        assert body["source"] == "vans-coding-router"
        logged_at = datetime.fromisoformat(body["log_time"])
        assert logged_at.tzinfo is not None and logged_at.utcoffset() is not None
        assert body["logger_name"] == example["logger_name"]
        assert body["message"] == example["message"]
    finally:
        forwarder.close()
        receiver.close()


def test_each_error_log_posts_again():
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    try:
        logging.getLogger("src.api").error("first failure")
        logging.getLogger("src.api").error("second failure")
        _wait_until(lambda: len(receiver.posts) >= 2)
        assert len(receiver.posts) == 2
        assert {post["body"]["message"] for post in receiver.posts} == {
            "first failure",
            "second failure",
        }
    finally:
        forwarder.close()
        receiver.close()


def test_exception_stack_is_kept_in_the_signal():
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    try:
        try:
            raise RuntimeError("secret traceback detail")
        except RuntimeError:
            logging.getLogger("src.presentation.portal").exception("Portal request failed")
        _wait_until(lambda: len(receiver.posts) >= 1)

        assert len(receiver.posts) == 1
        message = receiver.posts[0]["body"]["message"]
        assert message.startswith("Portal request failed\n")
        assert "Traceback (most recent call last):" in message
        assert "RuntimeError: secret traceback detail" in message
    finally:
        forwarder.close()
        receiver.close()


def test_warning_web_server_log_and_forwarder_log_produce_no_signal():
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    try:
        logging.getLogger("src.application.upstream_model_catalog").warning(
            "Upstream Model Catalog fetch failed: provider=openrouter kind=text"
        )
        logging.getLogger("uvicorn.error").error("web server failed")
        logging.getLogger("vans_signals_forwarder").error("Signal post failed: ConnectError")
        time.sleep(0.15)
        assert receiver.posts == []
    finally:
        forwarder.close()
        receiver.close()


def test_unset_destination_posts_nothing(monkeypatch):
    monkeypatch.delenv("VANS_SIGNALS_URL", raising=False)
    monkeypatch.delenv("VANS_SIGNALS_TOKEN", raising=False)
    receiver = _SignalsReceiver()
    try:
        assert start_signal_forwarding() is None
        assert start_signal_forwarding(receiver.url, "") is None
        assert start_signal_forwarding("", "router-token") is None
        logging.getLogger("src.api").error("should stay local")
        time.sleep(0.15)
        assert receiver.posts == []
    finally:
        receiver.close()


def test_student_request_does_not_wait_for_the_signal_post():
    receiver = _SignalsReceiver()
    receiver.hold_responses()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    app = FastAPI()

    @app.post("/v1/chat/completions")
    def chat():
        logging.getLogger("src.presentation.api").error("student path failed")
        return {"id": "chat"}

    try:
        client = TestClient(app)
        started = time.monotonic()
        response = client.post("/v1/chat/completions", json={"model": "vcr-auto"})
        elapsed = time.monotonic() - started
        assert response.status_code == 200
        assert elapsed < 0.5
        _wait_until(lambda: len(receiver.posts) >= 1)
        assert receiver.posts[0]["body"]["message"] == "student path failed"
    finally:
        receiver.release_responses()
        forwarder.close()
        receiver.close()


def test_a_failed_post_is_not_retried(caplog):
    receiver = _SignalsReceiver()
    receiver.fail_with(500)
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    try:
        with caplog.at_level(logging.ERROR, logger="vans_signals_forwarder"):
            logging.getLogger("src.api").error("delivery will fail")
            _wait_until(lambda: len(receiver.posts) >= 1 and bool(_failure_logs(caplog)))
        time.sleep(0.3)
        assert len(receiver.posts) == 1
        assert len(_failure_logs(caplog)) == 1
        assert "router-token" not in _failure_logs(caplog)[0].getMessage()
    finally:
        forwarder.close()
        receiver.close()


def test_shutdown_finishes_the_in_flight_post_before_the_process_can_exit():
    receiver = _SignalsReceiver()
    receiver.hold_responses()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None

    def release_after_the_request_is_in_flight():
        _wait_until(lambda: len(receiver.posts) >= 1)
        time.sleep(0.3)
        receiver.release_responses()

    releaser = threading.Thread(target=release_after_the_request_is_in_flight, daemon=True)
    releaser.start()
    try:
        logging.getLogger("src.boot").error("startup catalog round failed")
        started = time.monotonic()
        forwarder.close()
        forwarder = None
        elapsed = time.monotonic() - started
        assert elapsed >= 0.25
        assert len(receiver.posts) == 1
        assert receiver.posts[0]["body"]["message"] == "startup catalog round failed"
    finally:
        receiver.release_responses()
        if forwarder is not None:
            forwarder.close()
        releaser.join(timeout=2)
        receiver.close()


def test_a_dead_destination_gives_up_after_about_two_seconds(caplog):
    receiver = _SignalsReceiver()
    receiver.hold_responses()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    try:
        with caplog.at_level(logging.ERROR, logger="vans_signals_forwarder"):
            started = time.monotonic()
            logging.getLogger("src.api").error("destination is dead")
            assert time.monotonic() - started < 0.3
            _wait_until(lambda: bool(_failure_logs(caplog)), timeout=3.5)
        elapsed = time.monotonic() - started
        assert 1.5 <= elapsed <= 3.0
        assert len(receiver.posts) == 1
        time.sleep(0.2)
        assert len(receiver.posts) == 1
    finally:
        receiver.release_responses()
        forwarder.close()
        receiver.close()


def _student_key(tmp_path):
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(session_secret="test-secret"),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    gateway = FakeLLMGateway()
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=AuthUseCase(api_key_repo=repo))
    app.include_router(
        create_api_router(ApiUseCase(gateway=gateway, api_key_repo=repo, logger=FakeRequestLogger()))
    )
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "第一堂")
    student = repo.upsert_google_user("student@school.edu", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    return TestClient(app), gateway, redeem["api_key"]


def test_expected_refusal_produces_no_signal(tmp_path):
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    try:
        client, gateway, student_key = _student_key(tmp_path)
        blocked = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {student_key}"},
            json={"model": "openrouter@minimax/minimax-m3", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "model_not_allowed"
        assert gateway.last_nonstream_req is None
        time.sleep(0.15)
        assert receiver.posts == []
    finally:
        forwarder.close()
        receiver.close()


class _CatalogGateway:
    def __init__(self) -> None:
        self.down: set[str] = set()

    async def provider_models(self, provider, output_modalities=None):
        if provider in self.down:
            raise RuntimeError(f"{provider} down")
        return {"object": "list", "data": [{"id": "m", "name": "M", "provider": provider}]}


def _catalog_memory(gateway: _CatalogGateway) -> UpstreamModelCatalogMemory:
    settings = RouterSettings(
        providers={
            "openrouter": ProviderSettings(name="openrouter", enabled=True, base_url="https://openrouter.test/v1"),
            "ollama_cloud": ProviderSettings(name="ollama_cloud", enabled=True, base_url="https://ollama.test/v1"),
        }
    )
    return UpstreamModelCatalogMemory(lambda: settings, gateway, fetch_timeout_sec=0.2)


def test_catalog_round_with_failed_upstreams_posts_one_signal_naming_them():
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    gateway = _CatalogGateway()
    gateway.down = {"openrouter", "ollama_cloud"}
    memory = _catalog_memory(gateway)
    try:
        asyncio.run(memory.fill())
        _wait_until(lambda: len(receiver.posts) >= 1)
        assert len(receiver.posts) == 1
        message = receiver.posts[0]["body"]["message"]
        assert message.startswith(
            "Upstream Model Catalog round did not update: openrouter, ollama_cloud\n"
        )
        assert "Traceback (most recent call last):" in message
        assert "RuntimeError: openrouter down" in message
        assert "RuntimeError: ollama_cloud down" in message
        assert receiver.posts[0]["body"]["level"] == "ERROR"
    finally:
        forwarder.close()
        receiver.close()


def test_successful_catalog_round_and_a_later_success_post_nothing():
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None
    gateway = _CatalogGateway()
    memory = _catalog_memory(gateway)
    try:
        asyncio.run(memory.fill())
        time.sleep(0.15)
        assert receiver.posts == []

        gateway.down = {"ollama_cloud"}
        asyncio.run(memory.fill())
        _wait_until(lambda: len(receiver.posts) >= 1)
        assert len(receiver.posts) == 1
        assert "ollama_cloud" in receiver.posts[0]["body"]["message"]
        assert "openrouter" not in receiver.posts[0]["body"]["message"]

        gateway.down = set()
        asyncio.run(memory.fill())
        time.sleep(0.15)
        assert len(receiver.posts) == 1
    finally:
        forwarder.close()
        receiver.close()


def test_thrown_catalog_round_posts_the_existing_error_once():
    receiver = _SignalsReceiver()
    forwarder = start_signal_forwarding(receiver.url, "router-token")
    assert forwarder is not None

    class Portal:
        async def fill_upstream_model_catalog(self):
            raise RuntimeError("broken round")

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(
            run_upstream_model_catalog_refresh(Portal(), stop, interval_sec=1.0)
        )
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if receiver.posts:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("timed out")
            stop.set()
            await asyncio.sleep(0.3)
        finally:
            stop.set()
            await task

    try:
        asyncio.run(scenario())
        assert len(receiver.posts) == 1
        message = receiver.posts[0]["body"]["message"]
        assert message.startswith("Upstream Model Catalog refresh failed\n")
        assert "Traceback (most recent call last):" in message
        assert "RuntimeError: broken round" in message
        assert "did not update" not in message
    finally:
        forwarder.close()
        receiver.close()


def test_startup_catalog_round_that_throws_posts_that_error_once(monkeypatch):
    receiver = _SignalsReceiver()
    monkeypatch.setenv("VANS_SIGNALS_URL", receiver.url)
    monkeypatch.setenv("VANS_SIGNALS_TOKEN", "router-token")

    class Gateway:
        async def startup(self):
            return None

        async def shutdown(self):
            return None

    class Portal:
        async def fill_upstream_model_catalog(self):
            raise RuntimeError("broken round")

    container = SimpleNamespace(
        archive_repo=None,
        llm_gateway=Gateway(),
        portal_use_case=Portal(),
    )

    async def scenario():
        with pytest.raises(RuntimeError, match="broken round"):
            async with application_lifespan(container):
                pass

    try:
        asyncio.run(scenario())
        _wait_until(lambda: len(receiver.posts) >= 1)
        assert len(receiver.posts) == 1
        message = receiver.posts[0]["body"]["message"]
        assert message.startswith("Upstream Model Catalog refresh failed\n")
        assert "Traceback (most recent call last):" in message
        assert "RuntimeError: broken round" in message
        assert "did not update" not in message
    finally:
        receiver.close()


def test_process_forwards_an_error_emitted_while_it_is_up(monkeypatch):
    receiver = _SignalsReceiver()
    monkeypatch.setenv("VANS_SIGNALS_URL", receiver.url)
    monkeypatch.setenv("VANS_SIGNALS_TOKEN", "router-token")

    class Gateway:
        async def startup(self):
            return None

        async def shutdown(self):
            return None

    class Portal:
        async def fill_upstream_model_catalog(self):
            logging.getLogger("src.boot").error("boot failed")

    container = SimpleNamespace(
        archive_repo=None,
        llm_gateway=Gateway(),
        portal_use_case=Portal(),
    )

    async def scenario():
        async with application_lifespan(container):
            _wait_until(lambda: len(receiver.posts) >= 1)

    try:
        asyncio.run(scenario())
        assert len(receiver.posts) == 1
        assert receiver.posts[0]["body"]["message"] == "boot failed"
        assert receiver.posts[0]["authorization"] == "Bearer router-token"
    finally:
        receiver.close()
