"""Each teacher owns a Router Model Template."""

from src.domain.session_model_allowlist import VCROUTER_STENCIL
from src.infrastructure.vscode.merge_chat_language_models import load_vans_template
from test_extension_portal import _client, _portal_cookie

OWNER_ONLY = "ollama_cloud@owner-only:cloud"


def test_new_teacher_starts_from_the_shipped_text_shelf_starter(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")

    loaded = client.get(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    assert loaded.status_code == 200
    assert loaded.json() == load_vans_template()

    denied = client.get(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, student["id"]),
    )
    assert denied.status_code == 403
    assert repo.get_router_model_template(student["id"]) is None


def test_missing_teacher_template_row_is_stored_as_the_starter_copy(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    with repo._connect() as conn:
        conn.execute(repo._sql("DELETE FROM router_model_templates WHERE user_id = ?"), (teacher["id"],))
        missing = conn.execute(
            repo._sql("SELECT user_id FROM router_model_templates WHERE user_id = ?"),
            (teacher["id"],),
        ).fetchone()
    assert missing is None

    loaded = client.get(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    assert loaded.status_code == 200
    assert loaded.json() == load_vans_template()
    assert repo.get_router_model_template(teacher["id"]) == load_vans_template()


def test_save_forces_the_vcrouter_stencil_and_stays_on_that_teacher(tmp_path):
    client, repo, _ = _client(tmp_path)
    owner = repo.upsert_google_user("owner@school.edu", "Owner")
    other = repo.upsert_google_user("other@school.edu", "Other")
    saved = client.put(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, owner["id"]),
        json={
            "router_model_template": [
                {
                    "name": "Foreign",
                    "vendor": "openai",
                    "url": "https://evil.example/v1",
                    "models": [
                        {
                            "id": OWNER_ONLY,
                            "name": "Only owner",
                            "url": "https://evil.example/v1",
                            "requestHeaders": {"Authorization": "Bearer stolen"},
                        }
                    ],
                }
            ]
        },
    )
    assert saved.status_code == 200
    provider = saved.json()[0]
    assert provider["name"] == VCROUTER_STENCIL["name"]
    assert provider["vendor"] == VCROUTER_STENCIL["vendor"]
    assert provider["apiType"] == VCROUTER_STENCIL["apiType"]
    model = provider["models"][0]
    assert model["id"] == OWNER_ONLY
    assert model["name"] == "Only owner"
    assert model["url"] == VCROUTER_STENCIL["url"]
    assert model["requestHeaders"] == VCROUTER_STENCIL["requestHeaders"]

    other_view = client.get(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, other["id"]),
    )
    assert other_view.status_code == 200
    assert OWNER_ONLY not in other_view.text


def test_new_class_session_copies_the_owner_template_once(tmp_path):
    client, repo, _ = _client(tmp_path)
    owner = repo.upsert_google_user("owner@school.edu", "Owner")
    other = repo.upsert_google_user("other@school.edu", "Other")
    client.put(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, owner["id"]),
        json={
            "router_model_template": [
                {"name": "VCRouter", "models": [{"id": OWNER_ONLY, "name": "Only owner"}]}
            ]
        },
    )
    client.put(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, other["id"]),
        json={
            "router_model_template": [
                {
                    "name": "VCRouter",
                    "models": [{"id": "openrouter@other-only", "name": "Other"}],
                }
            ]
        },
    )
    klass = repo.create_class(owner["id"], "Demo", None, 2)
    created = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=_portal_cookie(repo, owner["id"]),
        json={"name": "Week 1"},
    )
    assert created.status_code == 200
    assert created.json()["session_chat_language_models"][0]["models"][0]["id"] == OWNER_ONLY

    client.put(
        "/teacher/router-model-template",
        cookies=_portal_cookie(repo, owner["id"]),
        json={
            "router_model_template": [
                {
                    "name": "VCRouter",
                    "models": [{"id": "ollama_cloud@later:cloud", "name": "Later"}],
                }
            ]
        },
    )
    listed = client.get(
        f"/teacher/classes/{klass['id']}/sessions/{created.json()['id']}",
        cookies=_portal_cookie(repo, owner["id"]),
    )
    assert listed.json()["session_chat_language_models"][0]["models"][0]["id"] == OWNER_ONLY
    assert "ollama_cloud@later:cloud" not in listed.text


def test_portal_page_loads_the_logged_in_teachers_template(tmp_path):
    client, _, _ = _client(tmp_path)
    page = client.get("/portal")
    assert page.status_code == 200
    assert "編輯模型範本" in page.text
    assert "/teacher/router-model-template" in page.text
    assert "api('/extension/chat-language-models')" not in page.text
