import base64
import io
import re
import zipfile

from src.infrastructure.vscode.install_vscode_models_script import (
    build_install_vscode_models_zip,
    render_install_vscode_models_cmd,
    render_install_vscode_models_command,
    render_install_vscode_models_script,
)


def test_render_install_script_contains_template_and_merge():
    script = render_install_vscode_models_script()
    assert "VCRouter" in script
    assert "Merge-ChatLanguageModels" in script
    assert "ollama_cloud@minimax-m3:cloud" in script
    assert '"maxInputTokens": 524288' in script
    assert "ExecutionPolicy Bypass" in script
    assert "Chat: Manage Language Models" in script


def test_render_install_cmd_uses_execution_policy_bypass():
    cmd = render_install_vscode_models_cmd()
    assert "ExecutionPolicy Bypass" in cmd
    assert ":VANS_PAYLOAD" in cmd
    assert "FromBase64String" in cmd
    assert "install-vscode-models.ps1 not found" not in cmd


def test_build_install_zip_contains_standalone_cmd():
    payload = build_install_vscode_models_zip()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert names == {"install-vscode-models.cmd"}
        content = archive.read("install-vscode-models.cmd").decode("utf-8")
    assert ":VANS_PAYLOAD" in content


def test_render_install_cmd_decodes_embedded_script():
    cmd = render_install_vscode_models_cmd()
    payload = re.split(r"(?m)^:VANS_PAYLOAD\s*\r?\n", cmd, maxsplit=1)[1].strip()
    decoded = base64.b64decode(payload).decode("utf-8")
    assert decoded == render_install_vscode_models_script()


def test_render_install_command_targets_macos_paths():
    script = render_install_vscode_models_command()
    assert script.startswith("#!/bin/bash\n")
    assert "python3" in script
    assert '"Library"' in script
    assert '"Application Support"' in script
    assert '"Code"' in script
    assert '"Code - Insiders"' in script
    assert "merge_chat_language_models" in script
    assert "b64decode" in script
    assert "Chat: Manage Language Models" in script
    assert "\r\n" not in script
    match = re.search(r"base64\.b64decode\('([A-Za-z0-9+/=]+)'\)", script)
    assert match
    decoded = base64.b64decode(match.group(1)).decode("utf-8")
    assert "ollama_cloud@minimax-m3:cloud" in decoded
    assert "VCRouter" in decoded
