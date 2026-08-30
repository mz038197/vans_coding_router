"""Unauthenticated Nickname Redeem over HTTP (extension path)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.routers.portal_router import create_portal_router


def _settings(tmp_path, **auth_kwargs) -> RouterSettings:
    return RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(
            teacher_domain="school.edu",
            admin_emails=("admin@school.edu",),
            session_secret="test-session-secret",
            dev_auth_enabled=True,
            **auth_kwargs,
        ),
    )


def _client(tmp_path, **auth_kwargs):
    settings = _settings(tmp_path, **auth_kwargs)
    repo = SqliteRouterRepository(settings.database.path, settings)
    app = FastAPI()
    app.include_router(create_portal_router(PortalUseCase(repo, settings), settings))
    return TestClient(
        app,
        base_url="http://127.0.0.1",
        headers={"Origin": settings.public_url},
    ), repo


def _portal_cookie(repo, user_id: int) -> dict[str, str]:
    token, _ = repo.create_portal_session(user_id, "Test browser")
    return {"vcr_portal_session": token}


def _live_session(repo):
    teacher = repo.upsert_google_user("teacher@school.edu", "Teacher")
    klass = repo.create_class(teacher["id"], "Demo", None, 2)
    session = repo.create_class_session(klass["id"], teacher["id"], "Week 1")
    return teacher, klass, session


def _redeem(client, invite_code: str, nickname: str):
    return client.post(
        "/extension/sessions/nickname-redeem",
        json={"invite_code": invite_code, "nickname": nickname},
    )


def test_nickname_redeem_returns_session_key_without_login(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    response = _redeem(client, session["invite_code"], "Ada")

    assert response.status_code == 200
    data = response.json()
    assert data["api_key"].startswith("vcr_sk_")
    assert data["session"]["invite_code"] == session["invite_code"]
    context = repo.verify_api_key_context(data["api_key"])
    assert context is not None
    assert context.session_id == session["id"]
    assert "session_user_id" not in response.cookies
    assert "session_user_id" not in (response.headers.get("set-cookie") or "")


def test_nickname_redeem_rejects_empty_after_trim(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    response = _redeem(client, session["invite_code"], "   ")

    assert response.status_code == 400


def test_nickname_redeem_rejects_nickname_longer_than_64(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    response = _redeem(client, session["invite_code"], "a" * 65)

    assert response.status_code == 400


def test_nickname_redeem_accepts_64_characters_after_trim(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    response = _redeem(client, session["invite_code"], "  " + ("b" * 64) + "  ")

    assert response.status_code == 200
    assert response.json()["api_key"].startswith("vcr_sk_")


def test_nickname_redeem_trims_ends_and_matches_exactly(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    first = _redeem(client, session["invite_code"], "  Ada  ")
    same = _redeem(client, session["invite_code"], "Ada")
    inner_space = _redeem(client, session["invite_code"], "A da")
    different_case = _redeem(client, session["invite_code"], "ada")

    assert first.status_code == 200
    assert same.json()["api_key"] == first.json()["api_key"]
    assert inner_space.json()["api_key"] != first.json()["api_key"]
    assert different_case.json()["api_key"] != first.json()["api_key"]


def test_nickname_redeem_same_class_session_returns_same_key(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    first = _redeem(client, session["invite_code"], "Ada")
    second = _redeem(client, session["invite_code"], "Ada")

    assert first.json()["api_key"] == second.json()["api_key"]


def test_nickname_redeem_same_class_later_session_is_same_user(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)

    first = _redeem(client, session["invite_code"], "Ada")
    first_user = repo.verify_api_key_context(first.json()["api_key"]).user_id
    repo.update_class_session(klass["id"], session["id"], status="ended")
    later = repo.create_class_session(klass["id"], teacher["id"], "Week 2")

    second = _redeem(client, later["invite_code"], "Ada")
    second_ctx = repo.verify_api_key_context(second.json()["api_key"])

    assert second.status_code == 200
    assert second_ctx.user_id == first_user
    assert second_ctx.session_id == later["id"]
    assert second.json()["api_key"] != first.json()["api_key"]


def test_nickname_redeem_same_string_in_other_class_is_different_user(tmp_path):
    client, repo = _client(tmp_path)
    teacher, _, session_a = _live_session(repo)
    klass_b = repo.create_class(teacher["id"], "Other", None, 2)
    session_b = repo.create_class_session(klass_b["id"], teacher["id"], "Week 1")

    a = _redeem(client, session_a["invite_code"], "Ada")
    b = _redeem(client, session_b["invite_code"], "Ada")

    user_a = repo.verify_api_key_context(a.json()["api_key"]).user_id
    user_b = repo.verify_api_key_context(b.json()["api_key"]).user_id
    assert user_a != user_b


def test_nickname_redeem_rejects_invalid_expired_and_ended_invite(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)

    invalid = _redeem(client, "NOPECODE", "Ada")
    assert invalid.status_code == 400

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    repo.update_class_session(klass["id"], session["id"], expires_at=past)
    expired = _redeem(client, session["invite_code"], "Ada")
    assert expired.status_code == 400

    live = repo.create_class_session(klass["id"], teacher["id"], "Week 2")
    repo.update_class_session(klass["id"], live["id"], status="ended")
    ended = _redeem(client, live["invite_code"], "Ada")
    assert ended.status_code == 400


def test_nickname_redeem_ignores_closed_open_registration(tmp_path):
    client, repo = _client(tmp_path, open_registration=False)
    _, _, session = _live_session(repo)

    response = _redeem(client, session["invite_code"], "Ada")

    assert response.status_code == 200
    assert response.json()["api_key"].startswith("vcr_sk_")


def test_nickname_redeem_does_not_store_typed_email_or_grant_admin(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    response = _redeem(client, session["invite_code"], "admin@school.edu")

    assert response.status_code == 200
    context = repo.verify_api_key_context(response.json()["api_key"])
    user = repo.get_user(context.user_id)
    assert user["email"] != "admin@school.edu"
    assert not user["email"].endswith("@school.edu")
    assert "admin" not in user["roles"]
    assert user["role"] == "student"
    assert context.is_admin is False


def test_portal_google_redeem_still_requires_session(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)

    unauthenticated = client.post("/sessions/redeem", json={"invite_code": session["invite_code"]})
    assert unauthenticated.status_code == 401

    student = repo.upsert_google_user("student@gmail.com", "Student")
    google = client.post(
        "/sessions/redeem",
        json={"invite_code": session["invite_code"]},
        cookies=_portal_cookie(repo, student["id"]),
    )
    assert google.status_code == 200
    assert google.json()["api_key"].startswith("vcr_sk_")


def test_session_list_counts_nickname_seats_not_google_redemptions(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    cookies = _portal_cookie(repo, teacher["id"])

    first = _redeem(client, session["invite_code"], "Ada")
    again = _redeem(client, session["invite_code"], "Ada")
    student = repo.upsert_google_user("student@gmail.com", "Student")
    google = client.post(
        "/sessions/redeem",
        json={"invite_code": session["invite_code"]},
        cookies=_portal_cookie(repo, student["id"]),
    )
    listing = client.get(f"/teacher/classes/{klass['id']}/sessions", cookies=cookies)

    assert first.status_code == 200
    assert again.status_code == 200
    assert google.status_code == 200
    item = listing.json()["items"][0]
    assert item["nickname_seat_count"] == 1
    assert item["redemption_count"] == 2
    assert item["seat_limit"] == 60


def test_nickname_redeem_rejects_new_nickname_when_seat_limit_reached(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    repo.update_class_session(klass["id"], session["id"], seat_limit=1)

    seated = _redeem(client, session["invite_code"], "Ada")
    rejected = _redeem(client, session["invite_code"], "Bob")

    assert seated.status_code == 200
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "此課堂座位已滿，無法以新暱稱領取"


def test_nickname_redeem_allows_rejoin_when_seat_limit_is_full(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    repo.update_class_session(klass["id"], session["id"], seat_limit=1)

    first = _redeem(client, session["invite_code"], "Ada")
    rejoin = _redeem(client, session["invite_code"], "Ada")
    blocked = _redeem(client, session["invite_code"], "Bob")

    assert first.status_code == 200
    assert rejoin.status_code == 200
    assert rejoin.json()["api_key"] == first.json()["api_key"]
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "此課堂座位已滿，無法以新暱稱領取"


def test_lowering_seat_limit_does_not_kick_existing_nicknames(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)

    ada = _redeem(client, session["invite_code"], "Ada")
    bob = _redeem(client, session["invite_code"], "Bob")
    repo.update_class_session(klass["id"], session["id"], seat_limit=1)

    ada_rejoin = _redeem(client, session["invite_code"], "Ada")
    bob_rejoin = _redeem(client, session["invite_code"], "Bob")
    charlie = _redeem(client, session["invite_code"], "Charlie")
    listing = client.get(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )

    assert ada.status_code == 200
    assert bob.status_code == 200
    assert ada_rejoin.status_code == 200
    assert bob_rejoin.status_code == 200
    assert ada_rejoin.json()["api_key"] == ada.json()["api_key"]
    assert bob_rejoin.json()["api_key"] == bob.json()["api_key"]
    assert repo.verify_api_key_context(ada.json()["api_key"]) is not None
    assert repo.verify_api_key_context(bob.json()["api_key"]) is not None
    assert charlie.status_code == 400
    assert charlie.json()["detail"] == "此課堂座位已滿，無法以新暱稱領取"
    item = listing.json()["items"][0]
    assert item["nickname_seat_count"] == 2
    assert item["seat_limit"] == 1


def test_google_redeem_succeeds_when_nickname_seats_are_full(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    repo.update_class_session(klass["id"], session["id"], seat_limit=1)
    seated = _redeem(client, session["invite_code"], "Ada")
    student = repo.upsert_google_user("student@gmail.com", "Student")

    google = client.post(
        "/sessions/redeem",
        json={"invite_code": session["invite_code"]},
        cookies=_portal_cookie(repo, student["id"]),
    )
    listing = client.get(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )

    assert seated.status_code == 200
    assert google.status_code == 200
    assert google.json()["api_key"].startswith("vcr_sk_")
    item = listing.json()["items"][0]
    assert item["nickname_seat_count"] == 1
    assert item["redemption_count"] == 2


def test_prior_session_nickname_takes_a_new_seat(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    first = _redeem(client, session["invite_code"], "Ada")
    repo.update_class_session(klass["id"], session["id"], status="ended")
    later = repo.create_class_session(klass["id"], teacher["id"], "Week 2")
    repo.update_class_session(klass["id"], later["id"], seat_limit=1)
    other = _redeem(client, later["invite_code"], "Bob")
    ada_again = _redeem(client, later["invite_code"], "Ada")

    assert first.status_code == 200
    assert other.status_code == 200
    assert ada_again.status_code == 400
    assert ada_again.json()["detail"] == "此課堂座位已滿，無法以新暱稱領取"


def test_extension_handoff_redeem_still_works(tmp_path):
    client, repo = _client(tmp_path)
    _, _, session = _live_session(repo)
    login = client.post(
        "/auth/google",
        json={"email": "student@gmail.com", "name": "Student", "client": "extension"},
    )
    redeem = client.post(
        "/extension/sessions/redeem",
        json={
            "handoff_token": login.json()["handoff_token"],
            "invite_code": session["invite_code"],
        },
    )
    assert redeem.status_code == 200
    assert redeem.json()["api_key"].startswith("vcr_sk_")


def test_class_redemptions_show_classroom_nickname_not_synthetic_email(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)

    redeem = _redeem(client, session["invite_code"], "Ada")
    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )

    assert redeem.status_code == 200
    assert listing.status_code == 200
    items = [item for item in listing.json()["items"] if item.get("redeemed_at")]
    assert len(items) == 1
    assert items[0]["name"] == "Ada"
    email = items[0].get("email")
    assert email in (None, "", "—") or "@" not in str(email)


def test_class_redemptions_keep_google_student_email(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    student = repo.upsert_google_user("student@gmail.com", "Student")
    google = client.post(
        "/sessions/redeem",
        json={"invite_code": session["invite_code"]},
        cookies=_portal_cookie(repo, student["id"]),
    )

    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )

    assert google.status_code == 200
    items = [item for item in listing.json()["items"] if item.get("redeemed_at")]
    assert len(items) == 1
    assert items[0]["name"] == "Student"
    assert items[0]["email"] == "student@gmail.com"
    assert not items[0].get("classroom_nickname")


def test_class_owner_can_inactivate_student_and_key_stops_working(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    redeem = _redeem(client, session["invite_code"], "Ada")
    api_key = redeem.json()["api_key"]
    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    student_id = [item for item in listing.json()["items"] if item.get("redeemed_at")][0]["user_id"]

    disable = client.patch(
        f"/teacher/classes/{klass['id']}/members/{student_id}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"status": "inactive"},
    )
    after = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )

    assert disable.status_code == 200
    assert disable.json()["status"] == "inactive"
    assert repo.verify_api_key_context(api_key) is None
    item = [row for row in after.json()["items"] if row.get("redeemed_at")][0]
    assert item["status"] == "inactive"
    assert item["name"] == "Ada"
    assert item["user_id"] == student_id


def test_inactive_student_cannot_nickname_redeem(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    first = _redeem(client, session["invite_code"], "Ada")
    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    student_id = [item for item in listing.json()["items"] if item.get("redeemed_at")][0]["user_id"]
    client.patch(
        f"/teacher/classes/{klass['id']}/members/{student_id}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"status": "inactive"},
    )

    again = _redeem(client, session["invite_code"], "Ada")

    assert first.status_code == 200
    assert again.status_code == 400
    assert again.json()["detail"] == "此暱稱已被停用，無法領取"


def test_admin_can_inactivate_class_member(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    admin = repo.upsert_google_user("admin@school.edu", "Admin")
    redeem = _redeem(client, session["invite_code"], "Ada")
    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, admin["id"]),
    )
    student_id = [item for item in listing.json()["items"] if item.get("redeemed_at")][0]["user_id"]

    disable = client.patch(
        f"/teacher/classes/{klass['id']}/members/{student_id}",
        cookies=_portal_cookie(repo, admin["id"]),
        json={"status": "inactive"},
    )

    assert redeem.status_code == 200
    assert listing.status_code == 200
    assert disable.status_code == 200
    assert disable.json()["status"] == "inactive"
    assert repo.verify_api_key_context(redeem.json()["api_key"]) is None


def test_other_teacher_cannot_inactivate_class_member(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    other = repo.upsert_google_user("other@school.edu", "Other")
    _redeem(client, session["invite_code"], "Ada")
    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    student_id = [item for item in listing.json()["items"] if item.get("redeemed_at")][0]["user_id"]

    forbidden = client.patch(
        f"/teacher/classes/{klass['id']}/members/{student_id}",
        cookies=_portal_cookie(repo, other["id"]),
        json={"status": "inactive"},
    )

    assert forbidden.status_code == 403
    assert repo.verify_api_key_context(
        _redeem(client, session["invite_code"], "Ada").json()["api_key"]
    ) is not None


def test_cannot_inactivate_student_from_another_class(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)
    other_class = repo.create_class(teacher["id"], "Other", None, 2)
    first = _redeem(client, session["invite_code"], "Ada")
    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )
    student_id = [item for item in listing.json()["items"] if item.get("redeemed_at")][0]["user_id"]

    rejected = client.patch(
        f"/teacher/classes/{other_class['id']}/members/{student_id}",
        cookies=_portal_cookie(repo, teacher["id"]),
        json={"status": "inactive"},
    )

    assert first.status_code == 200
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "此學生不在本課程中"
    assert repo.verify_api_key_context(first.json()["api_key"]) is not None


def test_collided_nicknames_remain_one_user_on_roster(tmp_path):
    client, repo = _client(tmp_path)
    teacher, klass, session = _live_session(repo)

    first = _redeem(client, session["invite_code"], "Ada")
    second = _redeem(client, session["invite_code"], "Ada")
    listing = client.get(
        f"/teacher/classes/{klass['id']}/redemptions",
        cookies=_portal_cookie(repo, teacher["id"]),
    )

    items = [item for item in listing.json()["items"] if item.get("redeemed_at")]
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["api_key"] == second.json()["api_key"]
    assert len(items) == 1
    assert items[0]["name"] == "Ada"
    user_a = repo.verify_api_key_context(first.json()["api_key"]).user_id
    user_b = repo.verify_api_key_context(second.json()["api_key"]).user_id
    assert user_a == user_b == items[0]["user_id"]
