# MCP Mirror - Unified Backend Launcher
# Usage: .\scripts\start_backend.ps1 [-Port 8000]

param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$projectNodeScript = Join-Path $ProjectRoot "scripts\use_project_node.ps1"

if (Test-Path $projectNodeScript) {
    . $projectNodeScript
    $projectNodeDir = Use-ProjectNodeLts -ProjectRoot $ProjectRoot
    if ($projectNodeDir) {
        Write-Host "Using project Node.js runtime: $projectNodeDir" -ForegroundColor Green
    }
}

try {
    chcp 65001 | Out-Null
} catch {
    # Best-effort only: explicit .NET/Python encodings below remain authoritative.
}
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:UVICORN_NO_USE_COLORS = "1"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  MCP Mirror - Backend Launcher" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Normalize runtime environment for MCP child processes.
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""
$env:NO_PROXY = "127.0.0.1,localhost"
$env:NPM_CONFIG_OFFLINE = "false"
$env:NPM_CONFIG_PREFER_OFFLINE = "false"
$env:NPM_CONFIG_CACHE = Join-Path $ProjectRoot "artifacts\npm_cache"
$env:UV_CACHE_DIR = Join-Path $ProjectRoot "artifacts\uv_cache"

# Ensure cache/memory directories exist.
New-Item -ItemType Directory -Force -Path `
    (Join-Path $ProjectRoot "artifacts\npm_cache"), `
    (Join-Path $ProjectRoot "artifacts\uv_cache"), `
    (Join-Path $ProjectRoot "artifacts\memory"), `
    (Join-Path $ProjectRoot "artifacts\logs") | Out-Null


# Load project .env so backend can read OPENROUTER/SILICONFLOW keys.
$dotEnvPath = Join-Path $ProjectRoot ".env"
if (Test-Path $dotEnvPath) {
    Get-Content $dotEnvPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) { return }
        $k = $parts[0].Trim()
        $v = $parts[1].Trim()
        if ($k) {
            Set-Item -Path "Env:$k" -Value $v
        }
    }
}

# Step 1: Activate venv if present
$venvActivate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    Write-Host "[1/4] Activating virtual environment..." -ForegroundColor Yellow
    & $venvActivate
} else {
    Write-Host "[1/4] .venv not found, using system Python" -ForegroundColor Yellow
}

# Step 2: Validate MCP config
Write-Host "[2/4] Validating MCP config..." -ForegroundColor Yellow
$validateScript = Join-Path $ProjectRoot "scripts\validate_config.py"
python $validateScript
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Config validation failed. Please fix errors before startup." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Ensure port is free
Write-Host "[3/4] Checking port $Port..." -ForegroundColor Yellow
$existingBackendProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -like '*uvicorn app:app*')
}

foreach ($process in $existingBackendProcesses) {
    if ($process.ProcessId -ne $PID) {
        Write-Host "Stopping stale backend-related process PID $($process.ProcessId)..." -ForegroundColor Yellow
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        } catch {
            Write-Host "Unable to stop PID $($process.ProcessId): $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

Start-Sleep -Milliseconds 800

$portInUse = netstat -ano | Select-String ":$Port\s.*LISTENING"
if ($portInUse) {
    $pidMatch = $portInUse[0] -match '\s+(\d+)\s*$'
    if ($pidMatch) {
        $portOwnerPid = $Matches[1]
        Write-Host "Port $Port is used by PID $portOwnerPid, releasing..." -ForegroundColor Yellow
        try {
            $taskkill = Start-Process -FilePath "taskkill" `
                -ArgumentList @("/PID", "$portOwnerPid", "/F") `
                -WindowStyle Hidden `
                -PassThru
            $null = $taskkill.WaitForExit(4000)
        } catch {
            Write-Host "taskkill failed for PID $portOwnerPid, continuing to verify port state..." -ForegroundColor Yellow
        }
        Start-Sleep -Seconds 1
    }
}
$portStillListening = netstat -ano | Select-String ":$Port\s.*LISTENING"
if ($portStillListening) {
    Write-Host "Port $Port is still occupied after release attempt." -ForegroundColor Red
    exit 1
}
Write-Host "Port $Port is available" -ForegroundColor Green
Write-Host ""

# Step 3.5: Ensure external CDAR FastMCP server is running
Write-Host "[3.5/4] Ensuring external CDAR FastMCP server..." -ForegroundColor Yellow
$externalStarter = Join-Path $ProjectRoot "scripts\start_external_mcp_servers.ps1"
if (Test-Path $externalStarter) {
    try {
        & $externalStarter
        Write-Host "External CDAR server check completed" -ForegroundColor Green
    } catch {
        Write-Host "External CDAR server startup failed: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Missing script: $externalStarter" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 4: Start backend
Write-Host "[4/4] Starting backend service..." -ForegroundColor Yellow
Write-Host "  URL:      http://localhost:$Port" -ForegroundColor Green
Write-Host "  API docs: http://localhost:$Port/docs" -ForegroundColor Green
Write-Host "  WebSocket: ws://localhost:$Port/ws/{client_id}" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

Set-Location (Join-Path $ProjectRoot "web_interface\backend")
python -m uvicorn app:app --host 0.0.0.0 --port $Port
