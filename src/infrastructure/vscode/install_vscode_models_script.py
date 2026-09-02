from __future__ import annotations

import base64
import io
import json
import zipfile
from typing import Any

from src.infrastructure.vscode.merge_chat_language_models import load_vans_template
from src.infrastructure.vscode.model_defaults import MODEL_PATCH_KEYS

_CMD_PAYLOAD_MARKER = ":VANS_PAYLOAD"
_CMD_PAYLOAD_SPLIT = "(?m)^:VANS_PAYLOAD\\r?\\n"


def _resolved_template(template: list[Any] | None) -> list[Any]:
    return template if template is not None else load_vans_template()


def render_install_vscode_models_command(template: list[Any] | None = None) -> str:
    """Self-contained macOS .command installer (double-click opens Terminal)."""
    template_b64 = base64.b64encode(
        json.dumps(_resolved_template(template), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    patch_keys_literal = ", ".join(repr(key) for key in MODEL_PATCH_KEYS)
    python_body = f"""
import base64
import copy
import json
from datetime import datetime
from pathlib import Path

TEMPLATE = json.loads(base64.b64decode({template_b64!r}).decode("utf-8"))
MODEL_PATCH_KEYS = ({patch_keys_literal},)


def patch_model_from_template(existing, template):
    for key in MODEL_PATCH_KEYS:
        if key not in existing and key in template:
            existing[key] = template[key]


def provider_key(provider):
    return provider.get("vendor"), provider.get("name")


def merge_chat_language_models(existing, template):
    merged = copy.deepcopy(existing or [])
    index = {{
        provider_key(provider): provider
        for provider in merged
        if isinstance(provider, dict)
    }}

    for template_provider in template:
        if not isinstance(template_provider, dict):
            continue
        key = provider_key(template_provider)
        if key not in index:
            merged.append(copy.deepcopy(template_provider))
            index[key] = merged[-1]
            continue

        target = index[key]
        existing_models = target.get("models")
        if not isinstance(existing_models, list):
            existing_models = []
            target["models"] = existing_models

        model_ids = {{
            model.get("id")
            for model in existing_models
            if isinstance(model, dict) and model.get("id")
        }}
        template_models = template_provider.get("models")
        if not isinstance(template_models, list):
            continue
        for template_model in template_models:
            if not isinstance(template_model, dict):
                continue
            model_id = template_model.get("id")
            if model_id and model_id in model_ids:
                for existing_model in existing_models:
                    if isinstance(existing_model, dict) and existing_model.get("id") == model_id:
                        patch_model_from_template(existing_model, template_model)
                        break
                continue
            existing_models.append(copy.deepcopy(template_model))
            if model_id:
                model_ids.add(model_id)

        allowed_ids = {{
            model.get("id")
            for model in template_models
            if isinstance(model, dict) and model.get("id")
        }}
        target["models"] = [
            model
            for model in existing_models
            if isinstance(model, dict) and model.get("id") in allowed_ids
        ]

    return merged


def install_edition(label, user_path):
    target = Path(user_path) / "chatLanguageModels.json"
    print(f"==> {{label}} : {{target}}")

    existing = []
    if target.is_file():
        raw = target.read_text(encoding="utf-8").strip()
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                existing = parsed
            elif isinstance(parsed, dict):
                existing = [parsed]
            else:
                raise SystemExit(f"Unexpected JSON type in {{target}}")

    merged = merge_chat_language_models(existing, TEMPLATE)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_name(f"{{target.name}}.bak.{{stamp}}")
        backup.write_bytes(target.read_bytes())
    target.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\\n",
        encoding="utf-8",
    )
    print(f"Updated {{target}}")


home = Path.home()
install_edition(
    "VS Code Stable",
    home / "Library" / "Application Support" / "Code" / "User",
)
install_edition(
    "VS Code Insiders",
    home / "Library" / "Application Support" / "Code - Insiders" / "User",
)

print("")
print("Next steps:")
print("1. Reload VS Code window (Developer: Reload Window)")
print("2. Chat: Manage Language Models -> update API Key with your vcr_sk_... key")
print("3. Pick the VCRouter model in Copilot (avoid Auto)")
"""
    # Keep LF endings for macOS Terminal / .command.
    return (
        "#!/bin/bash\n"
        'cd "$(dirname "$0")"\n'
        "set -uo pipefail\n"
        "\n"
        "if ! command -v python3 >/dev/null 2>&1; then\n"
        '  echo "python3 is required to merge chatLanguageModels.json."\n'
        '  echo "Install Python 3 from https://www.python.org/downloads/ or: xcode-select --install"\n'
        '  read -r -p "Press Enter to close..."\n'
        "  exit 1\n"
        "fi\n"
        "\n"
        "python3 - <<'PY'\n"
        f"{python_body.strip()}\n"
        "PY\n"
        "status=$?\n"
        "echo\n"
        'read -r -p "Press Enter to close..."\n'
        "exit $status\n"
    )


def render_install_vscode_models_cmd(template: list[Any] | None = None) -> str:
    ps1 = render_install_vscode_models_script(template)
    if _CMD_PAYLOAD_MARKER in ps1:
        raise ValueError("PowerShell script cannot contain the payload marker")
    payload = base64.b64encode(ps1.encode("utf-8")).decode("ascii")
    return (
        "@echo off\n"
        "chcp 65001 >nul\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
        "$raw = Get-Content -LiteralPath '%~f0' -Raw; "
        f"$b64 = ($raw -split '{_CMD_PAYLOAD_SPLIT}', 2)[1].Trim(); "
        "$path = Join-Path $env:TEMP 'vans-install-vscode-models.ps1'; "
        "[IO.File]::WriteAllBytes($path, [Convert]::FromBase64String($b64)); "
        "powershell -NoProfile -ExecutionPolicy Bypass -File $path; "
        "exit $LASTEXITCODE"
        "\"\n"
        "if errorlevel 1 pause\n"
        "exit /b\n"
        f"{_CMD_PAYLOAD_MARKER}\n"
        f"{payload}\n"
    )


def build_install_vscode_models_zip(template: list[Any] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("install-vscode-models.cmd", render_install_vscode_models_cmd(template))
    return buffer.getvalue()


def render_install_vscode_models_script(template: list[Any] | None = None) -> str:
    template_json = json.dumps(_resolved_template(template), ensure_ascii=False, indent=2)
    # Escape closing here-strings for PowerShell single-quoted here-string.
    template_json = template_json.replace("'", "''")

    return f"""#requires -Version 5.1
<#
.SYNOPSIS
  Merge Vans Coding Router models into VS Code chatLanguageModels.json without overwriting existing entries.
.NOTES
  Download install-vscode-models.cmd from Portal and double-click it.
  This .ps1 file is only for advanced/manual use with ExecutionPolicy Bypass.
#>
param(
    [ValidateSet('Stable', 'Insiders', 'Both')]
    [string]$Edition = 'Both',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

$TemplateJson = @'
{template_json}
'@

function Get-ProviderKey {{
    param($Provider)
    return @($Provider.vendor, $Provider.name)
}}

function Merge-ChatLanguageModels {{
    param(
        [AllowNull()]$Existing,
        [Parameter(Mandatory = $true)]$Template
    )

    if (-not $Existing) {{ $Existing = @() }}
    $merged = @()
    foreach ($item in $Existing) {{
        $merged += ($item | ConvertTo-Json -Depth 30 -Compress | ConvertFrom-Json)
    }}

    $index = @{{}}
    for ($i = 0; $i -lt $merged.Count; $i++) {{
        $key = (Get-ProviderKey $merged[$i]) -join "`0"
        $index[$key] = $i
    }}

    foreach ($templateProvider in $Template) {{
        $key = (Get-ProviderKey $templateProvider) -join "`0"
        if (-not $index.ContainsKey($key)) {{
            $merged += ($templateProvider | ConvertTo-Json -Depth 30 -Compress | ConvertFrom-Json)
            $index[$key] = $merged.Count - 1
            continue
        }}

        $target = $merged[$index[$key]]
        if (-not $target.models) {{ $target | Add-Member -NotePropertyName models -NotePropertyValue @() }}
        $modelIds = @{{}}
        foreach ($model in $target.models) {{
            if ($model.id) {{ $modelIds[$model.id] = $true }}
        }}
        foreach ($templateModel in $templateProvider.models) {{
            if ($templateModel.id -and $modelIds.ContainsKey($templateModel.id)) {{ continue }}
            $target.models += ($templateModel | ConvertTo-Json -Depth 30 -Compress | ConvertFrom-Json)
            if ($templateModel.id) {{ $modelIds[$templateModel.id] = $true }}
        }}
        $allowed = @{{}}
        foreach ($templateModel in @($templateProvider.models)) {{
            if ($templateModel.id) {{ $allowed[$templateModel.id] = $true }}
        }}
        $kept = @()
        foreach ($model in @($target.models)) {{
            if ($model.id -and $allowed.ContainsKey($model.id)) {{ $kept += $model }}
        }}
        $target.models = $kept
    }}

    return ,$merged
}}

function Install-Edition {{
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$UserPath
    )

    $target = Join-Path $UserPath 'chatLanguageModels.json'
    Write-Host "==> $Label : $target"

    $existing = @()
    if (Test-Path $target) {{
        $raw = Get-Content -Path $target -Raw -Encoding UTF8
        if ($raw.Trim()) {{
            $existing = @($raw | ConvertFrom-Json)
            if ($existing -isnot [System.Collections.IEnumerable] -or $existing -is [string]) {{
                $existing = @($existing)
            }}
        }}
    }}

    $template = @($TemplateJson | ConvertFrom-Json)
    $merged = Merge-ChatLanguageModels -Existing $existing -Template $template

    if ($WhatIf) {{
        Write-Host 'WhatIf: would write merged chatLanguageModels.json'
        return
    }}

    $parent = Split-Path $target -Parent
    if (-not (Test-Path $parent)) {{
        New-Item -ItemType Directory -Path $parent | Out-Null
    }}
    if (Test-Path $target) {{
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Copy-Item $target "$target.bak.$stamp"
    }}

    $json = $merged | ConvertTo-Json -Depth 30
    [System.IO.File]::WriteAllText($target, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Updated $target"
}}

$codeStable = Join-Path $env:APPDATA 'Code\\User'
$codeInsiders = Join-Path $env:APPDATA 'Code - Insiders\\User'

if ($Edition -in 'Stable', 'Both') {{
    Install-Edition -Label 'VS Code Stable' -UserPath $codeStable
}}
if ($Edition -in 'Insiders', 'Both') {{
    Install-Edition -Label 'VS Code Insiders' -UserPath $codeInsiders
}}

Write-Host ''
Write-Host 'Next steps:'
Write-Host '1. Reload VS Code window (Developer: Reload Window)'
Write-Host '2. Chat: Manage Language Models -> update API Key with your vcr_sk_... key'
Write-Host '3. Pick the VCRouter model in Copilot (avoid Auto)'
"""
