@echo off
chcp 65001 >nul
set "SCRIPT=%~dp0install-vscode-models.ps1"
if not exist "%SCRIPT%" (
  echo [ERROR] install-vscode-models.ps1 not found in %~dp0
  echo Download install-vscode-models.ps1 to the same folder, then run this file again.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
if errorlevel 1 pause
