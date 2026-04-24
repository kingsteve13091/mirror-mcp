# MCP Mirror - One-click local installer
# Usage:
#   .\scripts\install_system.ps1
#   .\scripts\install_system.ps1 -SkipFrontend
#   .\scripts\install_system.ps1 -SkipPython
#   .\scripts\install_system.ps1 -SkipNodeInstall

param(
    [switch]$SkipPython,
    [switch]$SkipFrontend,
    [switch]$SkipNodeInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$FrontendDir = Join-Path $ProjectRoot "web_interface\frontend"
$BackendRequirements = Join-Path $ProjectRoot "web_interface\backend\requirements.txt"
$RootRequirements = Join-Path $ProjectRoot "requirements.txt"
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"
$LogDir = Join-Path $ProjectRoot "artifacts\logs"

try {
    chcp 65001 | Out-Null
} catch {
    # Best-effort only.
}
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:NPM_CONFIG_CACHE = Join-Path $ProjectRoot "artifacts\npm_cache"
$env:UV_CACHE_DIR = Join-Path $ProjectRoot "artifacts\uv_cache"

New-Item -ItemType Directory -Force -Path `
    $LogDir, `
    (Join-Path $ProjectRoot "artifacts\npm_cache"), `
    (Join-Path $ProjectRoot "artifacts\uv_cache"), `
    (Join-Path $ProjectRoot "artifacts\memory"), `
    (Join-Path $ProjectRoot "artifacts\recipes"), `
    (Join-Path $ProjectRoot "artifacts\guards") | Out-Null

function Write-Step {
    param(
        [string]$Text
    )
    Write-Host ""
    Write-Host $Text -ForegroundColor Yellow
}

function Fail-Step {
    param(
        [string]$Text
    )
    Write-Host ""
    Write-Host $Text -ForegroundColor Red
    exit 1
}

function Get-CommandPathOrFail {
    param(
        [string]$Name,
        [string]$InstallHint
    )
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        Fail-Step "$Name not found. $InstallHint"
    }
    return $command.Source
}

function Ensure-PythonVenv {
    $pythonCommand = Get-CommandPathOrFail -Name "python" -InstallHint "Install Python 3.12+ and ensure it is on PATH."

    Write-Step "[1/7] Preparing Python virtual environment..."
    if (-not (Test-Path $VenvPython)) {
        & $pythonCommand -m venv $VenvDir
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
            Fail-Step "Failed to create virtual environment at $VenvDir"
        }
    }

    & $VenvPython -m pip install --upgrade pip wheel setuptools
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "Failed to upgrade pip tooling inside .venv"
    }
}

function Install-PythonDependencies {
    Write-Step "[2/7] Installing Python dependencies..."
    & $VenvPip install -r $RootRequirements
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "Failed to install root Python dependencies from requirements.txt"
    }

    if (Test-Path $BackendRequirements) {
        & $VenvPip install -r $BackendRequirements
        if ($LASTEXITCODE -ne 0) {
            Fail-Step "Failed to install backend Python dependencies"
        }
    }
}

function Validate-PythonRuntime {
    Write-Step "[3/7] Validating Python runtime..."
    & $VenvPython -c "import fastapi, fastmcp, mcp, uvicorn, websockets; print('python_runtime_ok')"
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "Python runtime validation failed"
    }
}

function Ensure-NodeToolchain {
    Get-CommandPathOrFail -Name "node" -InstallHint "Install Node.js 18+ and ensure node/npm/npx are on PATH." | Out-Null
    Get-CommandPathOrFail -Name "npm" -InstallHint "Install Node.js 18+ and ensure node/npm/npx are on PATH." | Out-Null
    Get-CommandPathOrFail -Name "npx" -InstallHint "Install Node.js 18+ and ensure node/npm/npx are on PATH." | Out-Null
    Get-CommandPathOrFail -Name "uvx" -InstallHint "Install uv and ensure uvx is on PATH, or install MCP Python tools another supported way." | Out-Null
}

function Install-FrontendDependencies {
    Write-Step "[4/7] Installing frontend dependencies..."
    Push-Location $FrontendDir
    try {
        if ($SkipNodeInstall) {
            Write-Host "Skipping npm install because -SkipNodeInstall was provided." -ForegroundColor DarkYellow
        } elseif (Test-Path (Join-Path $FrontendDir "package-lock.json")) {
            npm ci
            if ($LASTEXITCODE -ne 0) {
                Fail-Step "npm ci failed for frontend"
            }
        } else {
            npm install
            if ($LASTEXITCODE -ne 0) {
                Fail-Step "npm install failed for frontend"
            }
        }
    } finally {
        Pop-Location
    }
}

function Validate-NodeRuntime {
    Write-Step "[5/7] Validating Node/MCP toolchain..."
    Push-Location $FrontendDir
    try {
        npx tsc --noEmit
        if ($LASTEXITCODE -ne 0) {
            Fail-Step "Frontend TypeScript validation failed"
        }
    } finally {
        Pop-Location
    }
}

function Validate-ProjectConfig {
    Write-Step "[6/7] Validating project config..."
    & $VenvPython (Join-Path $ProjectRoot "scripts\validate_config.py")
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "Project config validation failed"
    }
}

function Summarize-Install {
    Write-Step "[7/7] Installation complete"
    Write-Host "Installed system components:" -ForegroundColor Green
    Write-Host "  Python env:   $VenvDir" -ForegroundColor Gray
    Write-Host "  Frontend dir: $FrontendDir" -ForegroundColor Gray
    Write-Host "  MCP config:   $(Join-Path $ProjectRoot 'mcp_config.json')" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Next commands:" -ForegroundColor Green
    Write-Host "  Backend : .\\scripts\\start_backend.ps1" -ForegroundColor Gray
    Write-Host "  Frontend: .\\scripts\\start_frontend.ps1" -ForegroundColor Gray
    Write-Host "  Smoke   : .\\scripts\\local_browser_runtime_check.ps1" -ForegroundColor Gray
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  MCP Mirror - One-click Installer" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray

if (-not $SkipPython) {
    Ensure-PythonVenv
    Install-PythonDependencies
    Validate-PythonRuntime
} else {
    Write-Step "[1-3/7] Skipping Python setup because -SkipPython was provided..."
}

if (-not $SkipFrontend) {
    Ensure-NodeToolchain
    Install-FrontendDependencies
    Validate-NodeRuntime
} else {
    Write-Step "[4-5/7] Skipping frontend setup because -SkipFrontend was provided..."
}

Validate-ProjectConfig
Summarize-Install
