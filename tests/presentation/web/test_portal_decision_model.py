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
    assert "delete next.decisionShelf" in html
    modal_at = html.index('id="editSessionChatModelsModal"')
    shelf_at = html.index('id="sessionDecisionShelf"')
    assert shelf_at > modal_at
