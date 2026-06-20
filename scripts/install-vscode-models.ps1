#requires -Version 5.1
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
[
  {
    "name": "VSRouter",
    "vendor": "customendpoint",
    "apiKey": "",
    "apiType": "responses",
    "models": [
      {
        "id": "ollama_cloud@minimax-m3:cloud",
        "name": "minimax-m3",
        "url": "https://ai.vanscoding.com/v1",
        "supportsReasoningEffort": [
          "none",
          "low",
          "medium",
          "high"
        ],
        "zeroDataRetentionEnabled": true,
        "toolCalling": true,
        "vision": true,
        "maxInputTokens": 128000,
        "maxOutputTokens": 16000
      },
      {
        "id": "ollama_cloud@qwen3.5:cloud",
        "name": "qwen3.5:cloud",
        "url": "https://ai.vanscoding.com/v1",
        "supportsReasoningEffort": [
          "none",
          "low",
          "medium",
          "high"
        ],
        "zeroDataRetentionEnabled": true,
        "toolCalling": true,
        "vision": true,
        "maxInputTokens": 128000,
        "maxOutputTokens": 16000
      },
      {
        "id": "ollama_cloud@nemotron-3-super:cloud",
        "name": "nemotron-3-super",
        "url": "https://ai.vanscoding.com/v1",
        "supportsReasoningEffort": [
          "none",
          "low",
          "medium",
          "high"
        ],
        "zeroDataRetentionEnabled": true,
        "toolCalling": true,
        "vision": false,
        "maxInputTokens": 128000,
        "maxOutputTokens": 16000
      }
    ]
  }
]
'@

function Get-ProviderKey {
    param($Provider)
    return @($Provider.vendor, $Provider.name)
}

function Merge-ChatLanguageModels {
    param(
        [AllowNull()]$Existing,
        [Parameter(Mandatory = $true)]$Template
    )

    if (-not $Existing) { $Existing = @() }
    $merged = @()
    foreach ($item in $Existing) {
        $merged += ($item | ConvertTo-Json -Depth 30 -Compress | ConvertFrom-Json)
    }

    $index = @{}
    for ($i = 0; $i -lt $merged.Count; $i++) {
        $key = (Get-ProviderKey $merged[$i]) -join "`0"
        $index[$key] = $i
    }

    foreach ($templateProvider in $Template) {
        $key = (Get-ProviderKey $templateProvider) -join "`0"
        if (-not $index.ContainsKey($key)) {
            $merged += ($templateProvider | ConvertTo-Json -Depth 30 -Compress | ConvertFrom-Json)
            $index[$key] = $merged.Count - 1
            continue
        }

        $target = $merged[$index[$key]]
        if (-not $target.models) { $target | Add-Member -NotePropertyName models -NotePropertyValue @() }
        $modelIds = @{}
        foreach ($model in $target.models) {
            if ($model.id) { $modelIds[$model.id] = $true }
        }
        foreach ($templateModel in $templateProvider.models) {
            if ($templateModel.id -and $modelIds.ContainsKey($templateModel.id)) { continue }
            $target.models += ($templateModel | ConvertTo-Json -Depth 30 -Compress | ConvertFrom-Json)
            if ($templateModel.id) { $modelIds[$templateModel.id] = $true }
        }
    }

    return ,$merged
}

function Install-Edition {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$UserPath
    )

    $target = Join-Path $UserPath 'chatLanguageModels.json'
    Write-Host "==> $Label : $target"

    $existing = @()
    if (Test-Path $target) {
        $raw = Get-Content -Path $target -Raw -Encoding UTF8
        if ($raw.Trim()) {
            $existing = @($raw | ConvertFrom-Json)
            if ($existing -isnot [System.Collections.IEnumerable] -or $existing -is [string]) {
                $existing = @($existing)
            }
        }
    }

    $template = @($TemplateJson | ConvertFrom-Json)
    $merged = Merge-ChatLanguageModels -Existing $existing -Template $template

    if ($WhatIf) {
        Write-Host 'WhatIf: would write merged chatLanguageModels.json'
        return
    }

    $parent = Split-Path $target -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    if (Test-Path $target) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Copy-Item $target "$target.bak.$stamp"
    }

    $json = $merged | ConvertTo-Json -Depth 30
    [System.IO.File]::WriteAllText($target, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Updated $target"
}

$codeStable = Join-Path $env:APPDATA 'Code\User'
$codeInsiders = Join-Path $env:APPDATA 'Code - Insiders\User'

if ($Edition -in 'Stable', 'Both') {
    Install-Edition -Label 'VS Code Stable' -UserPath $codeStable
}
if ($Edition -in 'Insiders', 'Both') {
    Install-Edition -Label 'VS Code Insiders' -UserPath $codeInsiders
}

Write-Host ''
Write-Host 'Next steps:'
Write-Host '1. Reload VS Code window (Developer: Reload Window)'
Write-Host '2. Chat: Manage Language Models -> update API Key with your vcr_sk_... key'
Write-Host '3. Pick the VSRouter model in Copilot (avoid Auto)'
