"""Upload and download carry Auto Tiers (#70).

The editor's upload sends the open draft and the file to
``POST /teacher/session-chat-language-models/upload``; the answer becomes the new draft,
which the teacher then saves as usual. Download is the draft as it stands, so it is the
saved document.
"""

import pytest

from test_auto_tier_save_checks import JEV, LIGHT, STRONG, TWO_TIERS, _document, _Saves, _tier

UPLOAD_URL = "/teacher/session-chat-language-models/upload"
TARGETS = pytest.mark.parametrize("target", ["sitting", "template"])


def _upload(saves, current, uploaded):
    return saves.client.post(
        UPLOAD_URL, cookies=saves.cookies, json={"current": current, "uploaded": uploaded}
    )


def _provider(document):
    assert len(document) == 1
    return document[0]


def _tier_of(document):
    return {model["id"]: model.get("autoTier") for model in _provider(document)["models"]}


@TARGETS
def test_an_uploaded_file_brings_its_tiers_and_model_tiers(tmp_path, target):
    saves = _Saves(tmp_path)
    current = saves.stored(target)

    response = _upload(saves, current, _document(tiers=TWO_TIERS))
    assert response.status_code == 200, response.text
    assert saves.save(target, response.json()).status_code == 200

    stored = saves.stored(target)
    assert _provider(stored)["autoTiers"] == TWO_TIERS
    assert _tier_of(stored) == {LIGHT: "t-light", STRONG: "t-strong"}


@TARGETS
def test_an_uploaded_selector_shelf_is_ignored(tmp_path, target):
    saves = _Saves(tmp_path)
    assert saves.save(target, _document(tiers=TWO_TIERS, selector=[JEV])).status_code == 200
    current = saves.stored(target)

    uploaded = _document(tiers=TWO_TIERS, selector=["openrouter@someone/else"])
    merged = _upload(saves, current, uploaded).json()
    assert saves.save(target, merged).status_code == 200

    assert _provider(saves.stored(target))["selectorShelf"] == [JEV]


@TARGETS
def test_an_uploaded_selector_shelf_is_ignored_when_the_draft_has_none(tmp_path, target):
    saves = _Saves(tmp_path)
    current = saves.stored(target)

    merged = _upload(saves, current, _document(tiers=TWO_TIERS, selector=[JEV])).json()

    assert "selectorShelf" not in _provider(merged)


@TARGETS
def test_download_then_upload_keeps_tiers_and_model_tiers(tmp_path, target):
    saves = _Saves(tmp_path)
    assert saves.save(target, _document(tiers=TWO_TIERS, selector=[JEV])).status_code == 200
    downloaded = saves.stored(target)

    merged = _upload(saves, downloaded, downloaded).json()
    assert saves.save(target, merged).status_code == 200

    assert saves.stored(target) == downloaded


def test_a_model_tier_the_tiers_do_not_name_is_dropped(tmp_path):
    saves = _Saves(tmp_path)
    models = [
        {"id": LIGHT, "name": "light", "autoTier": "t-light"},
        {"id": STRONG, "name": "strong", "autoTier": "t-gone"},
    ]

    merged = _upload(saves, saves.stored("sitting"), _document(tiers=TWO_TIERS, models=models))

    assert _tier_of(merged.json()) == {LIGHT: "t-light", STRONG: None}


def test_a_file_without_tiers_keeps_the_draft_tiers(tmp_path):
    saves = _Saves(tmp_path)
    current = _document(tiers=TWO_TIERS)
    models = [{"id": LIGHT, "name": "light", "autoTier": "t-strong"}]

    merged = _upload(saves, current, _document(models=models)).json()

    assert _provider(merged)["autoTiers"] == TWO_TIERS
    assert _tier_of(merged) == {LIGHT: "t-strong"}


def test_uploaded_models_land_on_the_text_shelf(tmp_path):
    saves = _Saves(tmp_path)
    models = [{"id": JEV, "name": "jev", "decisionShelf": True, "imageShelf": True}]

    merged = _upload(saves, saves.stored("sitting"), _document(models=models)).json()

    assert _provider(merged)["models"][0]["id"] == JEV
    assert "decisionShelf" not in _provider(merged)["models"][0]
    assert "imageShelf" not in _provider(merged)["models"][0]


def test_illegal_uploaded_tiers_are_refused_like_a_save(tmp_path):
    saves = _Saves(tmp_path)
    tiers = [_tier("a", "同名"), _tier("b", "同名")]

    response = _upload(saves, saves.stored("sitting"), _document(tiers=tiers, models=[]))

    assert response.status_code == 400
    assert response.json()["detail"] == "Tier 名稱「同名」重複"


def test_upload_is_for_teachers(tmp_path):
    saves = _Saves(tmp_path)
    student = saves.repo.upsert_google_user("student@gmail.com", "Student")
    cookies = {"vcr_portal_session": saves.repo.create_portal_session(student["id"], "b")[0]}

    response = saves.client.post(
        UPLOAD_URL, cookies=cookies, json={"current": [], "uploaded": _document()}
    )

    assert response.status_code == 403
