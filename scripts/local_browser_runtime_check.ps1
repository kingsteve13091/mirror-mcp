# MCP Mirror - repeatable local browser runtime check
# Usage:
#   .\scripts\local_browser_runtime_check.ps1
#
# Assumptions:
# - Backend is already running at http://127.0.0.1:8000
# - Frontend is already running at http://127.0.0.1:3000
# - Edge or Chrome is installed

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

try {
    chcp 65001 | Out-Null
} catch {
    # Best-effort only. The smoke script itself prints ASCII-only labels.
}

[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  MCP Mirror - Browser Runtime Check" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Backend:  http://127.0.0.1:8000" -ForegroundColor Gray
Write-Host "Frontend: http://127.0.0.1:3000" -ForegroundColor Gray
Write-Host ""

& $Python (Join-Path $ProjectRoot "scripts\browser_runtime_smoke.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Browser runtime check failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Browser runtime check passed." -ForegroundColor Green
