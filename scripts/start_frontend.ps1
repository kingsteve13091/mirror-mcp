# MCP Mirror - Unified Frontend Launcher
# Usage: .\scripts\start_frontend.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$FrontendDir = Join-Path $ProjectRoot "web_interface\frontend"
$Port = 3000
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
    # Best-effort only: explicit .NET/Node encodings below remain authoritative.
}
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:NODE_NO_WARNINGS = "0"

function Show-NodeCompatibilityWarning {
    $nodeVersionText = ""
    try {
        $nodeVersionText = (& node -v).Trim()
    } catch {
        Write-Host "Unable to determine Node.js version from PATH." -ForegroundColor Yellow
        return
    }

    $majorText = $nodeVersionText -replace '^v', ''
    $majorPart = $majorText.Split('.')[0]
    $majorVersion = 0

    if (-not [int]::TryParse($majorPart, [ref]$majorVersion)) {
        Write-Host "Unable to parse Node.js version: $nodeVersionText" -ForegroundColor Yellow
        return
    }

    if ($majorVersion -lt 18 -or $majorVersion -gt 22) {
        Write-Host "Node.js $nodeVersionText detected. react-scripts 5 is most stable on Node 18-22 LTS." -ForegroundColor Yellow
        Write-Host "If frontend startup becomes flaky, switch to Node 20 LTS or Node 22 LTS." -ForegroundColor Yellow
    } else {
        Write-Host "Node.js version: $nodeVersionText" -ForegroundColor Green
    }
}

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  MCP Mirror - Frontend Launcher" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Show-NodeCompatibilityWarning
Write-Host ""

# Step 1: Install deps if missing
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "[1/2] Installing frontend dependencies..." -ForegroundColor Yellow
    Set-Location $FrontendDir
    npm install
} else {
    Write-Host "[1/2] Frontend dependencies are ready" -ForegroundColor Green
}

# Step 2: Start frontend
Write-Host "[2/2] Starting frontend dev server..." -ForegroundColor Yellow
Write-Host "  URL: http://localhost:$Port" -ForegroundColor Green
Write-Host "  API -> http://localhost:8000" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

$frontendPort = netstat -ano | Select-String ":$Port\s.*LISTENING"
if ($frontendPort) {
    $pidMatch = $frontendPort[0] -match '\s+(\d+)\s*$'
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

$frontendStillListening = netstat -ano | Select-String ":$Port\s.*LISTENING"
if ($frontendStillListening) {
    Write-Host "Port $Port is still occupied after release attempt." -ForegroundColor Red
    exit 1
}

Set-Location $FrontendDir
npm start
