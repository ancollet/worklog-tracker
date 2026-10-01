# Builds a standalone Worklog.exe (no Python/uv needed by end users).
# Run on an actual Windows machine with uv installed: https://docs.astral.sh/uv/
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# Output: dist\Worklog\Worklog.exe (+ its dependency files, PyInstaller "onedir" mode).
# Next step: compile packaging\windows\installer.iss with Inno Setup to get a Setup.exe.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

uv sync --extra windows

uv run pyinstaller --noconfirm --windowed --name Worklog `
  --paths . `
  --collect-all PyQt6 `
  --add-data "worklog/resources/icons;worklog/resources/icons" `
  --hidden-import winreg `
  packaging/windows/run_worklog.py

Write-Host ""
Write-Host "Build fertig: dist\Worklog\Worklog.exe"
Write-Host "Naechster Schritt: installer.iss mit Inno Setup kompilieren (siehe README)."
