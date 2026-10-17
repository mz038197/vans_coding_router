"""Save checks for Auto Tiers and the selector shelf (ADR-0037, #69).

Every rule is checked on both saves: a sitting's Session Chat Language Models (PATCH)
and the teacher's Router Model Template (PUT). A refused save answers 400 with a
readable ``detail`` and leaves the stored document as it was.
"""

import pytest

from test_session_chat_language_models_editor import (
    _catalog_gateway,
    _classroom_providers,
    _client,
    _owner_session,
    _portal_cookie,
)

JEV = "openrouter@typesafe/jev-1.14"
LIGHT = "ollama_cloud@light:cloud"
STRONG = "ollama_cloud@strong:cloud"
IMAGE = "openrouter@google/image-1"


def _tier(tier_id, name, description="描述"):
    return {"id": tier_id, "name": name, "description": description}


TWO_TIERS = [_tier("t-light", "輕量", "語法小問題"), _tier("t-strong", "困難", "跨檔案除錯")]


def _document(*, tiers=None, selector=None, models=None):
    provider = {"name": "VCRouter", "vendor": "customendpoint"}
    if tiers is not None:
        provider["autoTiers"] = tiers
    if selector is not None:
        provider["selectorShelf"] = selector
    provider["models"] = (
        models
        if models is not None
        else [
            {"id": LIGHT, "name": "light", "autoTier": "t-light"},
            {"id": STRONG, "name": "strong", "autoTier": "t-strong"},
        ]
    )
    return [provider]


class _Saves:
    """One teacher with a sitting and a template, and a catalog whose decisions list holds JEV."""

    def __init__(self, tmp_path):
        gateway = _catalog_gateway()
        gateway.gateways["openrouter"].models_by_modality = {
            "decisions": {"object": "list", "data": [{"id": "typesafe/jev-1.14", "name": "Jev"}]},
        }
        self.client, self.repo, _ = _client(
            tmp_path, llm_gateway=gateway, providers=_classroom_providers()
        )
        teacher, klass, session = _owner_session(self.repo)
        self.cookies = _portal_cookie(self.repo, teacher["id"])
        self.session_url = f"/teacher/classes/{klass['id']}/sessions/{session['id']}"

    def save(self, target, document):
        if target == "sitting":
            return self.client.patch(
                self.session_url,
                cookies=self.cookies,
                json={"session_chat_language_models": document},
            )
        return self.client.put(
            "/teacher/router-model-template",
            cookies=self.cookies,
            json={"router_model_template": document},
        )

    def stored(self, target):
        if target == "sitting":
            return self.client.get(self.session_url, cookies=self.cookies).json()[
                "session_chat_language_models"
            ]
        return self.client.get("/teacher/router-model-template", cookies=self.cookies).json()

    def assert_refused(self, target, document, reason):
        before = self.stored(target)
        response = self.save(target, document)
        assert response.status_code == 400, response.text
        assert reason in response.json()["detail"]
        assert self.stored(target) == before


TARGETS = pytest.mark.parametrize("target", ["sitting", "template"])


@TARGETS
@pytest.mark.parametrize("count", [1, 7])
def test_tier_count_outside_two_to_six_is_refused(tmp_path, target, count):
    saves = _Saves(tmp_path)
    tiers = [_tier(f"t{i}", f"層{i}") for i in range(count)]

    saves.assert_refused(
        target, _document(tiers=tiers, models=[]), "難度數量必須是 2 到 6 個"
    )


@TARGETS
@pytest.mark.parametrize(
    ("tiers", "reason"),
    [
        ([_tier("a", "同名"), _tier("b", "同名")], "難度名稱「同名」重複"),
        ([_tier("a", "字" * 21), _tier("b", "短")], "難度名稱不可超過 20 字"),
        ([_tier("a", "   "), _tier("b", "短")], "難度名稱不可空白"),
        ([_tier("a", "空", "  "), _tier("b", "短")], "難度「空」的難度說明不可空白"),
        ([_tier("a", "長", "字" * 301), _tier("b", "短")], "難度「長」的難度說明不可超過 300 字"),
    ],
)
def test_tier_names_and_descriptions_are_checked(tmp_path, target, tiers, reason):
    saves = _Saves(tmp_path)

    saves.assert_refused(target, _document(tiers=tiers, models=[]), reason)


@TARGETS
def test_limits_are_inclusive_and_a_document_without_tiers_is_legal(tmp_path, target):
    saves = _Saves(tmp_path)
    six = [_tier(f"t{i}", f"{i}" + "字" * 19, "字" * 300) for i in range(6)]

    assert saves.save(target, _document(tiers=six, models=[])).status_code == 200
    assert saves.save(target, _document(tiers=[], models=[])).status_code == 200
    assert saves.save(target, _document(models=[{"id": LIGHT, "name": "light"}])).status_code == 200


@TARGETS
def test_a_model_tier_must_be_a_tier_of_this_document(tmp_path, target):
    saves = _Saves(tmp_path)
    models = [{"id": LIGHT, "name": "light", "autoTier": "t-elsewhere"}]

    saves.assert_refused(
        target, _document(tiers=TWO_TIERS, models=models), f"Model ID {LIGHT} 的難度不存在"
    )


@TARGETS
def test_renaming_a_tier_keeps_its_model_ids_on_it(tmp_path, target):
    saves = _Saves(tmp_path)
    assert saves.save(target, _document(tiers=TWO_TIERS, selector=[JEV])).status_code == 200
    renamed = [_tier("t-light", "入門", "語法小問題"), TWO_TIERS[1]]

    response = saves.save(target, _document(tiers=renamed, selector=[JEV]))

    assert response.status_code == 200, response.text
    stored = saves.stored(target)[0]
    assert [tier["name"] for tier in stored["autoTiers"]] == ["入門", "困難"]
    assert [m["autoTier"] for m in stored["models"]] == ["t-light", "t-strong"]


@TARGETS
def test_deleting_a_tier_that_still_holds_a_model_id_is_refused(tmp_path, target):
    saves = _Saves(tmp_path)
    three = [*TWO_TIERS, _tier("t-mid", "一般")]
    assert saves.save(target, _document(tiers=three)).status_code == 200

    saves.assert_refused(
        target,
        _document(tiers=[TWO_TIERS[0], three[2]]),
        f"難度「困難」還有 Model ID，不能刪除：{STRONG}",
    )
    moved = [
        {"id": LIGHT, "name": "light", "autoTier": "t-light"},
        {"id": STRONG, "name": "strong", "autoTier": "t-mid"},
    ]
    assert saves.save(target, _document(tiers=[TWO_TIERS[0], three[2]], models=moved)).status_code == 200


@TARGETS
def test_with_a_selector_every_text_shelf_model_id_needs_a_tier(tmp_path, target):
    saves = _Saves(tmp_path)
    models = [
        {"id": LIGHT, "name": "light", "autoTier": "t-light"},
        {"id": STRONG, "name": "strong"},
        {"id": IMAGE, "name": "image", "imageShelf": True},
    ]

    saves.assert_refused(
        target,
        _document(tiers=TWO_TIERS, selector=[JEV], models=models),
        f"自動選模架有 Model ID 時，每個對話模型都要有難度：{STRONG}",
    )
    assert saves.save(target, _document(tiers=TWO_TIERS, models=models)).status_code == 200


@TARGETS
def test_a_newly_checked_text_model_id_gets_no_tier(tmp_path, target):
    saves = _Saves(tmp_path)
    assert saves.save(target, _document(tiers=TWO_TIERS)).status_code == 200
    added = [
        {"id": LIGHT, "name": "light", "autoTier": "t-light"},
        {"id": STRONG, "name": "strong", "autoTier": "t-strong"},
        {"id": "ollama_cloud@new:cloud", "name": "new"},
    ]

    assert saves.save(target, _document(tiers=TWO_TIERS, models=added)).status_code == 200

    assert "autoTier" not in saves.stored(target)[0]["models"][2]


@TARGETS
def test_moving_a_tiered_model_id_to_the_image_shelf_clears_its_tier(tmp_path, target):
    saves = _Saves(tmp_path)
    assert saves.save(target, _document(tiers=TWO_TIERS)).status_code == 200
    moved = [
        {"id": LIGHT, "name": "light", "autoTier": "t-light"},
        {"id": STRONG, "name": "strong", "autoTier": "t-strong", "imageShelf": True},
    ]

    assert saves.save(target, _document(tiers=TWO_TIERS, models=moved)).status_code == 200

    stored = saves.stored(target)[0]["models"][1]
    assert stored["imageShelf"] is True
    assert "autoTier" not in stored


@TARGETS
def test_the_selector_shelf_takes_only_openrouter_decisions_list_ids(tmp_path, target):
    saves = _Saves(tmp_path)
    other = "openrouter@minimax/minimax-m3"

    saves.assert_refused(
        target,
        _document(tiers=TWO_TIERS, selector=[other]),
        f"自動選模架只接受 OpenRouter 決策清單的 Model ID：{other}",
    )
    models = [
        {"id": LIGHT, "name": "light", "autoTier": "t-light"},
        {"id": STRONG, "name": "strong", "autoTier": "t-strong"},
        {"id": JEV, "name": "jev", "decisionShelf": True},
    ]
    both = saves.save(target, _document(tiers=TWO_TIERS, selector=[JEV], models=models))
    assert both.status_code == 200, both.text
    stored = saves.stored(target)[0]
    assert stored["selectorShelf"] == [JEV]
    assert stored["models"][2]["decisionShelf"] is True


@TARGETS
def test_a_stored_selector_id_survives_a_catalog_that_no_longer_lists_it(tmp_path, target):
    saves = _Saves(tmp_path)
    assert saves.save(target, _document(tiers=TWO_TIERS, selector=[JEV])).status_code == 200
    saves.client.app.state.portal_use_case._upstream_catalog._snapshots.clear()

    renamed = [_tier("t-light", "入門", "語法小問題"), TWO_TIERS[1]]
    assert saves.save(target, _document(tiers=renamed, selector=[JEV])).status_code == 200
    saves.assert_refused(
        target,
        _document(tiers=renamed, selector=[JEV, "openrouter@typesafe/jev-2"]),
        "自動選模架只接受 OpenRouter 決策清單的 Model ID：openrouter@typesafe/jev-2",
    )
