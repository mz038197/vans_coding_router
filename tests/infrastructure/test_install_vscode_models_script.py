from src.infrastructure.vscode.install_vscode_models_script import render_install_vscode_models_script


def test_render_install_script_contains_template_and_merge():
    script = render_install_vscode_models_script()
    assert "VSRouter" in script
    assert "Merge-ChatLanguageModels" in script
    assert "ollama_cloud@qwen3-coder-next" in script
    assert "Chat: Manage Language Models" in script
