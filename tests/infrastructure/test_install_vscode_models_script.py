from src.infrastructure.vscode.install_vscode_models_script import (
    build_install_vscode_models_zip,
    render_install_vscode_models_cmd,
    render_install_vscode_models_script,
)
import zipfile
import io


def test_render_install_script_contains_template_and_merge():
    script = render_install_vscode_models_script()
    assert "VSRouter" in script
    assert "Merge-ChatLanguageModels" in script
    assert "ollama_cloud@qwen3-coder-next" in script
    assert "ExecutionPolicy Bypass" in script
    assert "Chat: Manage Language Models" in script


def test_render_install_cmd_uses_execution_policy_bypass():
    cmd = render_install_vscode_models_cmd()
    assert "ExecutionPolicy Bypass" in cmd
    assert ":PS1" in cmd
    assert "VSRouter" in cmd
    assert "install-vscode-models.ps1 not found" not in cmd


def test_build_install_zip_contains_standalone_cmd():
    payload = build_install_vscode_models_zip()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert names == {"install-vscode-models.cmd"}
        content = archive.read("install-vscode-models.cmd").decode("utf-8")
    assert ":PS1" in content
