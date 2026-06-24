#requires -Version 5.1
<#
.SYNOPSIS
  Deploy vans-coding-router to Fly.io (first-time setup + deploy).
.NOTES
  Prerequisites:
  1. flyctl: winget install Fly-io.flyctl
  2. fly auth login
  3. DATABASE_URL (Render External URL or Neon) — see guide/FLY_DEPLOYMENT.md
  4. Secrets in $HOME\.vans_coding_router\fly.secrets.env (copy from fly.secrets.env.example)
#>
param(
    [switch]$SecretsOnly,
    [switch]$SkipSecrets,
    [string]$AppName = 'vans-coding-router'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$SecretsFile = Join-Path $HOME '.vans_coding_router\fly.secrets.env'
$ExampleSecrets = Join-Path $RepoRoot 'config\fly.secrets.env.example'

function Get-FlyCmd {
    foreach ($name in @('fly', 'flyctl')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $wingetFly = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\Fly-io.flyctl_Microsoft.Winget.Source_8wekyb3d8bbwe\flyctl.exe'
    if (Test-Path $wingetFly) { return $wingetFly }
    Write-Host 'flyctl not found. Install: winget install Fly-io.flyctl' -ForegroundColor Yellow
    Write-Host 'Then restart the terminal and run this script again.'
    exit 1
}

function Invoke-Fly {
    param(
        [Parameter(Mandatory)]
        [string[]]$FlyArgs,
        [switch]$Quiet
    )
    $fly = Get-FlyCmd
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # flyctl writes benign warnings to stderr; do not treat them as script errors.
        $raw = & $fly @FlyArgs 2>&1
        $code = $LASTEXITCODE
        $lines = @($raw | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() }
            else { "$_" }
        })
        $lines = @($lines | Where-Object {
            $_ -and $_ -notmatch 'Metrics token unavailable'
        })
        if (-not $Quiet) {
            foreach ($line in $lines) {
                Write-Host $line
            }
        }
        return @{
            ExitCode = $code
            Lines    = $lines
            Text     = ($lines -join [Environment]::NewLine)
        }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Test-FlyAuth {
    $result = Invoke-Fly -FlyArgs @('auth', 'whoami') -Quiet
    $loggedIn = ($result.ExitCode -eq 0) -or ($result.Text -match '@')
    if (-not $loggedIn) {
        Write-Host 'Not logged in to Fly.io. Run: flyctl auth login' -ForegroundColor Yellow
        exit 1
    }
    if ($result.Text.Trim()) {
        Write-Host "Fly.io: $($result.Text.Trim())"
    }
}

function Ensure-SecretsFile {
    if (Test-Path $SecretsFile) { return }
    $dir = Split-Path $SecretsFile -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    if (Test-Path $ExampleSecrets) {
        Copy-Item $ExampleSecrets $SecretsFile
        Write-Host "Created $SecretsFile — fill in values, then re-run." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Missing $SecretsFile — see guide/FLY_DEPLOYMENT.md" -ForegroundColor Yellow
    exit 1
}

function Read-SecretsLines {
    param([string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $text = [System.Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    } else {
        $text = [System.IO.File]::ReadAllText($Path)
    }
    if ($text.Length -gt 0 -and [int][char]$text[0] -eq 0xFEFF) {
        $text = $text.Substring(1)
    }
    return @($text -split "`r?`n" | ForEach-Object { $_.Trim().Trim([char]0xFEFF) } | Where-Object {
        $_ -and $_ -notmatch '^\s*#' -and $_ -match '='
    } | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $name = $Matches[1].Trim().Trim([char]0xFEFF)
            "$name=$($Matches[2])"
        } else {
            $_
        }
    })
}

function Import-FlySecrets {
    Ensure-SecretsFile
    $payload = Read-SecretsLines -Path $SecretsFile
    if (-not $payload) {
        Write-Host "No secrets in $SecretsFile" -ForegroundColor Yellow
        exit 1
    }
    # Do NOT pipe to `fly secrets import` — PowerShell adds UTF-8 BOM to stdin.
    $setArgs = @('secrets', 'set')
    foreach ($line in $payload) {
        if ($line -match '^([^=]+)=(.*)$') {
            $name = $Matches[1].Trim().Trim([char]0xFEFF)
            if ($name -match '[^\w]') {
                Write-Host "Invalid secret name: $name" -ForegroundColor Yellow
                exit 1
            }
            $setArgs += "$name=$($Matches[2])"
        }
    }
    if ($setArgs.Count -le 2) {
        Write-Host "No KEY=value secrets parsed from $SecretsFile" -ForegroundColor Yellow
        exit 1
    }
    $setArgs += '--app', $AppName
    Write-Host "Setting Fly secrets on $AppName ($($setArgs.Count - 3) keys) ..."
    $result = Invoke-Fly -FlyArgs $setArgs
    if ($result.ExitCode -ne 0) { exit $result.ExitCode }
}

Set-Location $RepoRoot
Test-FlyAuth

$list = Invoke-Fly -FlyArgs @('apps', 'list') -Quiet
if ($list.Text -notmatch [regex]::Escape($AppName)) {
    Write-Host "Creating Fly app $AppName ..."
    $created = Invoke-Fly -FlyArgs @('apps', 'create', $AppName)
    if ($created.ExitCode -ne 0) { exit $created.ExitCode }
}

if (-not $SkipSecrets) {
    Import-FlySecrets
}

if ($SecretsOnly) {
    Write-Host 'Secrets updated.'
    exit 0
}

Write-Host 'Deploying to Fly.io ...'
$deploy = Invoke-Fly -FlyArgs @('deploy', '--app', $AppName)
exit $deploy.ExitCode
