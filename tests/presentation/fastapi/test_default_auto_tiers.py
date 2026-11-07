"""Shipped default Auto Tiers (ADR-0037, #72)."""

from test_extension_portal import _client, _portal_cookie

DEFAULT_TIERS = [
    {
        "id": "light",
        "name": "輕量",
        "description": (
            "簡單、範圍小的協助：解釋觀念、語法或錯誤訊息的意思、改寫一兩行程式、翻譯或整理文字。"
            "不需要找出錯誤原因，也不需要寫新的功能。"
        ),
    },
    {
        "id": "standard",
        "name": "一般",
        "description": (
            "一般的程式作業：撰寫或修改一個函式或小功能、找出並修正一小段程式裡原因明確的錯誤、"
            "補寫測試、檢查或重構一小段程式碼。"
        ),
    },
    {
        "id": "hard",
        "name": "困難",
        "description": (
            "困難或開放式的工作：跨多個檔案的設計、找出原因不明的錯誤、規劃大型修改、"
            "推敲複雜的演算法或效能問題。"
        ),
    },
]


def test_new_teacher_template_starts_with_the_three_default_tiers(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")

    loaded = client.get("/teacher/router-model-template", cookies=_portal_cookie(repo, teacher["id"]))

    assert loaded.status_code == 200
    assert loaded.json()[0]["autoTiers"] == DEFAULT_TIERS


def _without_tiers(document: list) -> list:
    return [{k: v for k, v in provider.items() if k != "autoTiers"} for provider in document]


def test_existing_templates_and_sittings_are_not_given_the_default_tiers(tmp_path):
    _, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    old_document = _without_tiers(repo.get_router_model_template(teacher["id"]))
    repo.save_router_model_template(teacher["id"], old_document)
    repo.update_class_session(klass["id"], session["id"], session_chat_language_models=old_document)

    restarted, repo, _ = _client(tmp_path)
    cookies = _portal_cookie(repo, teacher["id"])

    template = restarted.get("/teacher/router-model-template", cookies=cookies).json()
    sitting = restarted.get(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}", cookies=cookies
    ).json()["session_chat_language_models"]
    assert template == old_document
    assert sitting == old_document


def test_teacher_reads_the_current_default_tiers(tmp_path):
    client, repo, _ = _client(tmp_path)
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    student = repo.upsert_google_user("student@gmail.com", "Student")

    loaded = client.get("/teacher/auto-tier-defaults", cookies=_portal_cookie(repo, teacher["id"]))
    denied = client.get("/teacher/auto-tier-defaults", cookies=_portal_cookie(repo, student["id"]))
    anonymous = client.get("/teacher/auto-tier-defaults")

    assert loaded.status_code == 200
    assert loaded.json() == {"items": DEFAULT_TIERS}
    assert denied.status_code == 403
    assert anonymous.status_code == 401
