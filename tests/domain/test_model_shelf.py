from src.domain.decision_model import is_decision_shelf_model
from src.domain.model_shelf import is_image_shelf_model


def test_shelf_check_qualifies_a_non_openrouter_model():
    decision = {"id": "ollama_cloud@kimi-k3:cloud", "decisionShelf": True}
    image = {"id": "openai@gpt-4o", "imageShelf": True}
    assert is_decision_shelf_model(decision) is True
    assert is_image_shelf_model(image) is True
    assert is_decision_shelf_model({"id": "openrouter@minimax/minimax-m3"}) is False
    assert is_image_shelf_model({"id": "openrouter@minimax/minimax-m3"}) is False
