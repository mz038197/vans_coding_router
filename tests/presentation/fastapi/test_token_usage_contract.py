"""Token Usage, end to end: API calls in, the teacher's usage endpoint out."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, PromptLogSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from src.presentation.fastapi.routers.portal_router import create_portal_router
from fakes import FakeLLMGateway, FakeRequestLogger

CHAT_BODY = {
    "model": "ollama_cloud@minimax-m3:cloud",
    "messages": [{"role": "user", "content": "hello"}],
}


class World:
    def __init__(self, tmp_path):
        settings = RouterSettings(
            path=str(tmp_path / "router.yaml"),
            public_url="http://testserver",
            database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
            auth=AuthSettings(session_secret="test-secret"),
            # Archive Age 0: an archive run moves every existing Prompt Log.
            prompt_logs=PromptLogSettings(archive_after_days=0, delete_after_days=30),
        )
        self.repo = repo = SqliteRouterRepository(settings.database.path, settings)
        gateway = FakeLLMGateway()
        gateway.nonstream_response = {
            **gateway.nonstream_response,
            "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
        }
        app = FastAPI()
        register_error_handlers(app)
        app.add_middleware(ApiKeyMiddleware, auth_use_case=AuthUseCase(api_key_repo=repo))
        app.include_router(create_api_router(ApiUseCase(gateway=gateway, api_key_repo=repo, logger=FakeRequestLogger())))
        app.include_router(create_portal_router(PortalUseCase(repo, settings), settings))
        self.client = TestClient(app, headers={"Origin": "http://testserver"})

        self.admin = repo.upsert_google_user("admin@school.edu", "Admin")
        repo.update_user(self.admin["id"], roles=["admin"])
        self.teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
        repo.update_user(self.teacher["id"], roles=["teacher"])
        self.klass = repo.create_class(self.teacher["id"], "AI 素養", None, 2)
        self.session = repo.create_class_session(self.klass["id"], self.teacher["id"], "第一堂")
        with repo._connect() as conn:
            conn.execute(
                repo._sql("UPDATE class_sessions SET classroom_model_choice = NULL WHERE id = ?"),
                (self.session["id"],),
            )

    def cookie(self, user: dict) -> dict[str, str]:
        token, _ = self.repo.create_portal_session(user["id"], "Test browser")
        return {"vcr_portal_session": token}

    def student(self, email: str) -> tuple[dict, str]:
        user = self.repo.upsert_google_user(email, email.split("@")[0])
        key = self.repo.redeem_invite(self.session["invite_code"], user["id"])["api_key"]
        return user, key

    def chat(self, key: str) -> int:
        return self.client.post(
            "/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=CHAT_BODY
        ).status_code

    def set_prompt_logging(self, enabled: bool) -> None:
        response = self.client.patch(
            f"/teacher/classes/{self.klass['id']}/sessions/{self.session['id']}",
            cookies=self.cookie(self.teacher),
            json={"prompt_logging_enabled": enabled},
        )
        assert response.status_code == 200, response.text

    def usage(self) -> dict[int, dict]:
        response = self.client.get(f"/teacher/classes/{self.klass['id']}/usage", cookies=self.cookie(self.teacher))
        assert response.status_code == 200, response.text
        return {row["user_id"]: row for row in response.json()["items"]}

    def prompt_logs(self) -> list[dict]:
        response = self.client.get(
            f"/teacher/classes/{self.klass['id']}/prompt-logs", cookies=self.cookie(self.teacher)
        )
        assert response.status_code == 200, response.text
        return response.json()["items"]


def test_usage_grows_when_prompt_logging_is_off_and_no_prompt_log_is_stored(tmp_path):
    world = World(tmp_path)
    student, key = world.student("student@gmail.com")
    world.set_prompt_logging(False)

    assert world.chat(key) == 200

    row = world.usage()[student["id"]]
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (11, 22, 33)
    assert row["sessions"][0]["total_tokens"] == 33
    assert world.prompt_logs() == []


def test_a_rejected_request_is_not_counted(tmp_path):
    world = World(tmp_path)
    student, key = world.student("student@gmail.com")
    assert world.chat(key) == 200
    disabled = world.client.patch(
        f"/teacher/classes/{world.klass['id']}/members/{student['id']}",
        cookies=world.cookie(world.teacher),
        json={"status": "inactive"},
    )
    assert disabled.status_code == 200, disabled.text

    assert world.chat(key) in (401, 403)

    row = world.usage()[student["id"]]
    assert (row["total_tokens"], row["request_count"]) == (33, 1)


def test_usage_reports_each_students_request_count(tmp_path):
    world = World(tmp_path)
    busy, busy_key = world.student("busy@gmail.com")
    quiet, quiet_key = world.student("quiet@gmail.com")
    idle, _ = world.student("idle@gmail.com")
    for _ in range(3):
        assert world.chat(busy_key) == 200
    assert world.chat(quiet_key) == 200

    usage = world.usage()

    assert [usage[u["id"]]["request_count"] for u in (busy, quiet, idle)] == [3, 1, 0]
    assert usage[busy["id"]]["total_tokens"] == 99
    assert usage[busy["id"]]["sessions"][0]["request_count"] == 3


def test_archiving_prompt_logs_leaves_usage_unchanged(tmp_path):
    world = World(tmp_path)
    student, key = world.student("student@gmail.com")
    assert world.chat(key) == 200
    assert world.chat(key) == 200
    assert len(world.prompt_logs()) == 2

    archived = world.client.post("/admin/archive/run", cookies=world.cookie(world.admin))
    assert archived.status_code == 200
    assert archived.json()["archived"] == 2
    assert world.prompt_logs() == []

    row = world.usage()[student["id"]]
    assert (row["total_tokens"], row["request_count"]) == (66, 2)


def test_deleting_a_users_prompt_logs_also_deletes_their_usage(tmp_path):
    world = World(tmp_path)
    gone, gone_key = world.student("gone@gmail.com")
    kept, kept_key = world.student("kept@gmail.com")
    world.set_prompt_logging(False)
    assert world.chat(gone_key) == 200
    world.set_prompt_logging(True)
    assert world.chat(gone_key) == 200
    assert world.chat(kept_key) == 200

    deleted = world.client.post(
        "/admin/prompt-logs/delete", cookies=world.cookie(world.admin), json={"user_ids": [gone["id"]]}
    )

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted_live": 1, "deleted_archive": 0, "deleted_token_usage": 2}
    usage = world.usage()
    assert (usage[gone["id"]]["total_tokens"], usage[gone["id"]]["request_count"]) == (0, 0)
    assert usage[kept["id"]]["request_count"] == 1


def test_a_personal_api_key_request_is_recorded_without_a_class(tmp_path):
    world = World(tmp_path)
    student, classroom_key = world.student("student@gmail.com")
    # The teacher joins their own sitting too, so the course usage lists them.
    world.repo.redeem_invite(world.session["invite_code"], world.teacher["id"])
    personal_key = world.repo.issue_long_lived_key(world.teacher["id"])

    assert world.chat(personal_key) == 200
    assert world.chat(classroom_key) == 200

    # No class, so the course usage does not include it ...
    usage = world.usage()
    assert usage[world.teacher["id"]]["request_count"] == 0
    assert usage[student["id"]]["request_count"] == 1
    # ... but it was recorded: deleting the holder's data removes exactly that one row.
    deleted = world.client.post(
        "/admin/prompt-logs/delete", cookies=world.cookie(world.admin), json={"user_ids": [world.teacher["id"]]}
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_token_usage"] == 1
