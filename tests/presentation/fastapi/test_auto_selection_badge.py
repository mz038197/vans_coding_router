"""The class-list 「自動選模」 badge condition (ADR-0037, #73).

Each session row carries ``auto_selection_active``: true when the sitting is on
Automatic Models, its selector shelf holds a Model ID, and its text shelf uses at
least two tiers. The Portal shows the badge from this one field.
"""

import pytest

from test_session_chat_language_models_editor import _client, _owner_session, _portal_cookie

JEV = "openrouter@typesafe/jev-1.14"
LIGHT = "ollama_cloud@light:cloud"
STRONG = "ollama_cloud@strong:cloud"
TIERS = [
    {"id": "t-light", "name": "輕量", "description": "語法小問題"},
    {"id": "t-strong", "name": "困難", "description": "跨檔案除錯"},
]


def _document(*, selector, strong_tier="t-strong"):
    return [
        {
            "name": "VCRouter",
            "vendor": "customendpoint",
            "autoTiers": TIERS,
            "selectorShelf": selector,
            "models": [
                {"id": LIGHT, "name": "light", "autoTier": "t-light"},
                {"id": STRONG, "name": "strong", "autoTier": strong_tier},
            ],
        }
    ]


def _row(tmp_path, document, choice):
    client, repo, _ = _client(tmp_path)
    teacher, klass, session = _owner_session(repo)
    repo.update_class_session(
        klass["id"],
        session["id"],
        session_chat_language_models=document,
        classroom_model_choice=choice,
    )
    cookies = _portal_cookie(repo, teacher["id"])
    listed = client.get(f"/teacher/classes/{klass['id']}/sessions", cookies=cookies)
    one = client.get(f"/teacher/classes/{klass['id']}/sessions/{session['id']}", cookies=cookies)
    assert listed.status_code == 200 and one.status_code == 200
    (row,) = listed.json()["items"]
    assert row["auto_selection_active"] == one.json()["auto_selection_active"]
    return row


def test_badge_is_on_for_automatic_models_with_a_selector_and_two_tiers_used(tmp_path):
    row = _row(tmp_path, _document(selector=[JEV]), "automatic")

    assert row["auto_selection_active"] is True


@pytest.mark.parametrize(
    ("document", "choice"),
    [
        pytest.param(_document(selector=[JEV]), "picked", id="picked-models"),
        pytest.param(_document(selector=[]), "automatic", id="empty-selector-shelf"),
        pytest.param(_document(selector=[JEV], strong_tier="t-light"), "automatic", id="one-tier-used"),
    ],
)
def test_badge_is_off_when_a_condition_fails(tmp_path, document, choice):
    row = _row(tmp_path, document, choice)

    assert row["auto_selection_active"] is False
