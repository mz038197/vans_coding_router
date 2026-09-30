from pathlib import Path


def test_portal_moves_decision_model_into_classroom_models():
    html = Path("src/presentation/fastapi/web/portal.html").read_text(encoding="utf-8")
    assert "學生用程式送決策" not in html
    assert "decision_enabled" not in html
    assert "DECISION_MODEL_SHELF" not in html
    assert "decision_model_allowlist" not in html
    assert 'id="sessionDecisionModel"' not in html
    assert 'id="sessionDecisionShelf"' in html
    assert "output_modalities=" in html
    assert "option value=\"image\">生圖" in html
    assert "imageShelf" in html
    assert "speechShelf" in html
    assert "speechTranscriptionShelf" in html
    assert "全部" in html
    assert 'id="sessionAllModelsShelf"' in html
    assert "指定架" in html
    assert "sessionHasShelf(session, 'imageShelf')" in html
    assert "sessionHasShelf(session, 'decisionShelf')" in html
    assert "sessionHasShelf(session, 'imageShelf', true)" not in html
    assert "sessionHasShelf(session, 'decisionShelf', true)" not in html
    all_models = html.split('id="sessionAllModelsShelf"', 1)[1].split("</select>", 1)[0]
    assert 'value="decisions"' not in all_models
    assert 'value="image"' not in all_models
    assert "session-image-toggle" not in html
    assert "session-tts-toggle" not in html
    assert "clearShelfFlags" in html
    modal_at = html.index('id="editSessionChatModelsModal"')
    shelf_at = html.index('id="sessionDecisionShelf"')
    assert shelf_at > modal_at
