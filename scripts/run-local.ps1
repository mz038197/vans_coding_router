# Local dev server (Google OAuth via ~/.vans_coding_router/router.yaml)
$ErrorActionPreference = "Stop"

$configDir = Join-Path $HOME ".vans_coding_router"
$configPath = Join-Path $configDir "router.yaml"

if (-not (Test-Path $configPath)) {
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    Copy-Item (Join-Path $PSScriptRoot "..\config\router.example.yaml") $configPath -Force
    Write-Host "Created $configPath"
}

$env:VCR_CONFIG = $configPath
$env:PUBLIC_URL = "http://127.0.0.1:8000"

Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Set-Location (Join-Path $PSScriptRoot "..")
Write-Host "VCR_CONFIG=$env:VCR_CONFIG"
Write-Host "PUBLIC_URL=$env:PUBLIC_URL"
Write-Host "Portal: http://127.0.0.1:8000/portal"
Write-Host "OAuth check: http://127.0.0.1:8000/auth/config"

uv run uvicorn app:app --reload --host 127.0.0.1 --port 8000
