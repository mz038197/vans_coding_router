from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.lobby_use_case import LobbyHostUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.lobby.registry import ConnectionHub, RoomRegistry
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.lobby_router import create_lobby_router


def _settings(tmp_path: Path) -> RouterSettings:
    return RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-session-secret",
        ),
    )


def _lobby_client(tmp_path: Path):
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    portal = PortalUseCase(repo, settings)
    workspace = tmp_path / "lobby"
    registry = RoomRegistry(workspace)
    registry.load_from_disk()
    hub = ConnectionHub()
    lobby = LobbyHostUseCase(workspace, registry, hub)
    app = FastAPI()
    app.include_router(create_lobby_router(lobby, portal, settings))
    return TestClient(app), repo


def _teacher_cookie(client: TestClient, repo) -> dict[str, str]:
    user = repo.upsert_google_user(email="teacher@school.edu", name="Teacher")
    repo.update_user(user["id"], roles=["teacher"])
    return {"session_user_id": str(user["id"])}


def _student_cookie(client: TestClient, repo) -> dict[str, str]:
    user = repo.upsert_google_user(email="student@gmail.com", name="Student")
    return {"session_user_id": str(user["id"])}


def test_lobby_page_requires_teacher(tmp_path):
    client, repo = _lobby_client(tmp_path)
    assert client.get("/lobby").status_code == 403
    assert client.get("/lobby", cookies=_student_cookie(client, repo)).status_code == 403
    response = client.get("/lobby", cookies=_teacher_cookie(client, repo))
    assert response.status_code == 200
    assert "Agent Lobby" in response.text or "Agent" in response.text


def test_create_and_list_rooms_creator_only(tmp_path):
    client, repo = _lobby_client(tmp_path)
    teacher_cookies = _teacher_cookie(client, repo)
    other = repo.upsert_google_user(email="other@school.edu", name="Other")
    repo.update_user(other["id"], roles=["teacher"])

    create = client.post("/lobby/api/rooms", json={"room_id": "ROOM-A"}, cookies=teacher_cookies)
    assert create.status_code == 200

    listed = client.get("/lobby/api/rooms", cookies=teacher_cookies)
    assert listed.status_code == 200
    assert [r["room_id"] for r in listed.json()["items"]] == ["ROOM-A"]

    other_list = client.get("/lobby/api/rooms", cookies={"session_user_id": str(other["id"])})
    assert other_list.json()["items"] == []


def test_admin_sees_all_rooms(tmp_path):
    client, repo = _lobby_client(tmp_path)
    teacher_cookies = _teacher_cookie(client, repo)
    client.post("/lobby/api/rooms", json={"room_id": "ROOM-X"}, cookies=teacher_cookies)

    admin = repo.upsert_google_user(email="admin@school.edu", name="Admin")
    admin_list = client.get("/lobby/api/rooms", cookies={"session_user_id": str(admin["id"])})
    assert admin_list.status_code == 200
    assert [r["room_id"] for r in admin_list.json()["items"]] == ["ROOM-X"]


def test_portal_css_served(tmp_path):
    client, _ = _lobby_client(tmp_path)
    response = client.get("/portal/static/portal.css")
    assert response.status_code == 200
    assert "--accent:" in response.text
