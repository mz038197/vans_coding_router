"""The Upstream Model Catalog lives in process memory."""

import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import application_lifespan
from src.application.upstream_model_catalog import (
    CATALOG_FETCH_TIMEOUT_SEC,
    CATALOG_REFRESH_INTERVAL_SEC,
)
from src.infrastructure.jobs.upstream_model_catalog_job import run_upstream_model_catalog_refresh
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.portal_router import create_portal_router
from test_session_chat_language_models_editor import (
    _catalog_gateway,
    _classroom_providers,
    _client,
    _owner_session,
    _portal_cookie,
    _settings,
)
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template

_OPENROUTER_KINDS = ("text", "decisions", "image", "speech", "transcription")


def _record_catalog_fetches(gateway):
    calls: list[tuple[str, str | None]] = []
    in_flight = {"n": 0, "peak": 0}

    for name, inner in gateway.gateways.items():
        original = inner.models

        async def models(*args, _original=original, _name=name, **kwargs):
            in_flight["n"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["n"])
            calls.append((_name, kwargs.get("output_modalities")))
            await asyncio.sleep(0)
            try:
                return await _original(*args, **kwargs)
            finally:
                in_flight["n"] -= 1

        inner.models = models
    return calls, in_flight


def test_fetch_limits_are_thirty_seconds_and_thirty_minutes():
    assert CATALOG_FETCH_TIMEOUT_SEC == 30
    assert CATALOG_REFRESH_INTERVAL_SEC == 30 * 60


def test_process_fills_the_catalog_before_it_accepts_requests(tmp_path):
    events: list[str] = []
    gateway = _catalog_gateway()
    settings = _settings(tmp_path, providers=_classroom_providers())
    repo = SqliteRouterRepository(settings.database.path, settings)
    portal = PortalUseCase(repo, settings, llm_gateway=gateway)
    original_fill = portal.fill_upstream_model_catalog

    async def fill():
        events.append("fill-start")
        await original_fill()
        events.append("fill-done")

    portal.fill_upstream_model_catalog = fill
    container = SimpleNamespace(
        archive_repo=None,
        llm_gateway=gateway,
        portal_use_case=portal,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with application_lifespan(container):
            events.append("accept")
            yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_portal_router(portal, settings))
    with TestClient(app, base_url="http://127.0.0.1", headers={"Origin": settings.public_url}) as client:
        assert events.index("fill-done") < events.index("accept")
        teacher, _, _ = _owner_session(repo)
        response = client.get(
            "/teacher/upstream-model-catalog",
            cookies=_portal_cookie(repo, teacher["id"]),
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["models"]] == ["openrouter@minimax/minimax-m3"]


def test_startup_fetches_each_portion_once_together_and_a_read_does_not_fetch_again(tmp_path):
    gateway = _catalog_gateway()
    calls, in_flight = _record_catalog_fetches(gateway)
    client, repo, _ = _client(tmp_path, llm_gateway=gateway, providers=_classroom_providers())
    teacher, _, _ = _owner_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])

    assert in_flight["peak"] == 7
    openrouter_kinds = [kind for name, kind in calls if name == "openrouter"]
    assert openrouter_kinds == list(_OPENROUTER_KINDS)
    assert [kind for name, kind in calls if name == "ollama_cloud"] == [None]
    assert [kind for name, kind in calls if name == "openai"] == [None]
    startup_calls = len(calls)

    text = client.get("/teacher/upstream-model-catalog", cookies=cookies)
    everything = client.get(
        "/teacher/upstream-model-catalog?output_modalities=all",
        cookies=cookies,
    )
    assert text.status_code == 200
    assert [item["id"] for item in text.json()["models"]] == ["openrouter@minimax/minimax-m3"]
    assert [item["id"] for item in everything.json()["models"]] == [
        "ollama_cloud@minimax-m3:cloud",
        "openai@gpt-4o-mini-tts",
    ]
    assert len(calls) == startup_calls


def test_a_timed_out_portion_stays_unavailable_and_saved_models_stay_editable(tmp_path):
    gateway = _catalog_gateway()
    openrouter = gateway.gateways["openrouter"]
    original = openrouter.models

    async def slow_models(*args, **kwargs):
        await asyncio.sleep(2)
        return await original(*args, **kwargs)

    openrouter.models = slow_models
    started = time.monotonic()
    client, repo, _ = _client(
        tmp_path,
        llm_gateway=gateway,
        providers=_classroom_providers(),
        catalog_fetch_timeout_sec=0.05,
    )
    assert time.monotonic() - started < 1
    teacher, klass, session = _owner_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])

    catalog = client.get("/teacher/upstream-model-catalog", cookies=cookies)
    assert catalog.status_code == 200
    assert catalog.json()["unavailable"] is True
    assert catalog.json()["models"] == []
    assert catalog.json()["providers"] == ["openrouter"]

    everything = client.get(
        "/teacher/upstream-model-catalog?output_modalities=all",
        cookies=cookies,
    )
    assert [item["id"] for item in everything.json()["models"]] == [
        "ollama_cloud@minimax-m3:cloud",
        "openai@gpt-4o-mini-tts",
    ]
    stored = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
    )
    assert stored.json()["session_chat_language_models"] == load_vans_template()


def test_failed_refresh_keeps_the_last_successful_snapshot(tmp_path):
    gateway = _catalog_gateway()
    client, repo, _ = _client(tmp_path, llm_gateway=gateway, providers=_classroom_providers())
    teacher, _, _ = _owner_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])
    openrouter = gateway.gateways["openrouter"]

    async def fail_models(*args, **kwargs):
        raise RuntimeError("upstream /models down")

    openrouter.models = fail_models
    asyncio.run(client.app.state.portal_use_case.fill_upstream_model_catalog())

    catalog = client.get("/teacher/upstream-model-catalog", cookies=cookies)
    assert catalog.json()["unavailable"] is False
    assert [item["id"] for item in catalog.json()["models"]] == ["openrouter@minimax/minimax-m3"]


def test_successful_refresh_replaces_that_portion(tmp_path):
    gateway = _catalog_gateway()
    client, repo, _ = _client(tmp_path, llm_gateway=gateway, providers=_classroom_providers())
    teacher, _, _ = _owner_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])
    gateway.gateways["openrouter"].models_response = {
        "object": "list",
        "data": [{"id": "new/model", "name": "New"}],
    }
    asyncio.run(client.app.state.portal_use_case.fill_upstream_model_catalog())

    catalog = client.get("/teacher/upstream-model-catalog", cookies=cookies)
    assert [item["id"] for item in catalog.json()["models"]] == ["openrouter@new/model"]


def test_refresh_does_not_change_stored_model_ids_shelves_or_order(tmp_path):
    gateway = _catalog_gateway()
    client, repo, _ = _client(tmp_path, llm_gateway=gateway, providers=_classroom_providers())
    teacher, klass, session = _owner_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])
    document = [
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "models": [
                {"id": "openrouter@kept-text", "name": "Kept text"},
                {"id": "openai@kept-speech", "name": "Kept speech", "speechShelf": True},
                {"id": "openrouter@kept-decision", "name": "Kept decision", "decisionShelf": True},
            ],
        }
    ]
    saved_session = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
        json={"session_chat_language_models": document},
    )
    assert saved_session.status_code == 200
    saved_template = client.put(
        "/teacher/router-model-template",
        cookies=cookies,
        json={"router_model_template": document},
    )
    assert saved_template.status_code == 200
    gateway.gateways["openrouter"].models_response = {
        "object": "list",
        "data": [{"id": "replaced/model", "name": "Replaced"}],
    }
    asyncio.run(client.app.state.portal_use_case.fill_upstream_model_catalog())

    session_again = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
    )
    template_again = client.get("/teacher/router-model-template", cookies=cookies)
    assert session_again.json()["session_chat_language_models"] == saved_session.json()["session_chat_language_models"]
    assert template_again.json() == saved_template.json()
    stored_ids = [model["id"] for model in session_again.json()["session_chat_language_models"][0]["models"]]
    assert stored_ids == ["openrouter@kept-text", "openai@kept-speech", "openrouter@kept-decision"]
    flags = session_again.json()["session_chat_language_models"][0]["models"]
    assert flags[1]["speechShelf"] is True
    assert flags[2]["decisionShelf"] is True


def test_personal_api_key_lists_and_calls_do_not_use_catalog_memory(tmp_path):
    gateway = _catalog_gateway()
    calls, _in_flight = _record_catalog_fetches(gateway)
    client, repo, _ = _client(tmp_path, llm_gateway=gateway, providers=_classroom_providers())
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    repo.update_user(teacher["id"], roles=["teacher"])
    repo.save_router_model_template(
        teacher["id"],
        [{"name": "VCRouter", "models": [{"id": "openai@teacher-only", "name": "Teacher only"}]}],
    )
    api_key = repo.issue_long_lived_key(teacher["id"])
    headers = {"Authorization": f"Bearer {api_key}"}
    startup_calls = len(calls)

    listed = client.get("/v1/models", headers=headers)
    chat = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "openai@teacher-only", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert [item["id"] for item in listed.json()["data"]] == ["vcr-auto", "openai@teacher-only"]
    assert "openrouter@minimax/minimax-m3" not in listed.text
    assert chat.status_code == 200
    assert client.app.state.api_gateway.last_nonstream_req.model == "openai@teacher-only"
    assert len(calls) == startup_calls


def test_catalog_refresh_waits_out_its_interval(tmp_path):
    fills: list[float] = []

    class Portal:
        async def fill_upstream_model_catalog(self):
            fills.append(time.monotonic())

    stop = asyncio.Event()

    async def run():
        await run_upstream_model_catalog_refresh(Portal(), stop, interval_sec=0.05)

    async def scenario():
        started = time.monotonic()
        task = asyncio.create_task(run())
        await asyncio.sleep(0.12)
        stop.set()
        await task
        assert fills
        assert fills[0] - started >= 0.04

    asyncio.run(scenario())
