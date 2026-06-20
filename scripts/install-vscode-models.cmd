@echo off
chcp 65001 >nul
set "SCRIPT=%~dp0install-vscode-models.ps1"
if not exist "%SCRIPT%" (
  echo [ERROR] install-vscode-models.ps1 not found in %~dp0
  echo Extract the zip and run this file from the same folder.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
if errorlevel 1 pause
