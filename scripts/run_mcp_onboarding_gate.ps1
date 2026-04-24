# MCP Mirror - one-click onboarding regression gate
# Usage:
#   .\scripts\run_mcp_onboarding_gate.ps1
#
# Assumptions:
# - Backend is already running at http://127.0.0.1:8000
# - Frontend is already running at http://127.0.0.1:3000

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

try {
    chcp 65001 | Out-Null
} catch {
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
Write-Host "  MCP Mirror - Onboarding Regression Gate" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Backend:  http://127.0.0.1:8000" -ForegroundColor Gray
Write-Host "Frontend: http://127.0.0.1:3000" -ForegroundColor Gray
Write-Host ""

& $Python (Join-Path $ProjectRoot "scripts\mcp_onboarding_gate.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Onboarding regression gate failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Onboarding regression gate passed." -ForegroundColor Green
