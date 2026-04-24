# MCP Mirror - Start only the external CDAR FastMCP server

param(
    [switch]$KillExisting,
    [int]$KillTimeoutMs = 4000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$FastMcp = Join-Path $ProjectRoot ".venv\Scripts\fastmcp.exe"

[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

if (-not (Test-Path $Python)) {
    $Python = "python"
}
if (-not (Test-Path $FastMcp)) {
    $FastMcp = "fastmcp"
}

try {
    chcp 65001 | Out-Null
} catch {
    # Best-effort only: explicit .NET/Python encodings below remain authoritative.
}

# Load project .env so CDAR can access model API keys.
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

$cdar = @{ Name = "cdar_mcp"; Script = "cdar_mcp.py"; Port = 9001; Log = "cdar_mcp" }
$legacyPorts = @(9002, 9003, 9004, 9005)
$logDir = Join-Path $ProjectRoot "artifacts\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Stop-ListeningPort {
    param(
        [int]$Port
    )

    $listen = netstat -ano | Select-String ":$Port\s.*LISTENING"
    if (-not $listen) {
        return
    }

    $m = $listen[0] -match '\s+(\d+)\s*$'
    if (-not $m) {
        return
    }

    $targetPid = $Matches[1]
    try {
        $taskkill = Start-Process -FilePath "taskkill" `
            -ArgumentList @("/PID", "$targetPid", "/F") `
            -WindowStyle Hidden `
            -PassThru
        $null = $taskkill.WaitForExit($KillTimeoutMs)
        if (-not $taskkill.HasExited) {
            Write-Host "[WARN] taskkill timeout on PID $targetPid, continue..." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[WARN] taskkill failed for PID $targetPid, continue..." -ForegroundColor Yellow
    }
    Start-Sleep -Milliseconds 300
}

if ($KillExisting) {
    Stop-ListeningPort -Port $cdar.Port
    foreach ($legacyPort in $legacyPorts) {
        Stop-ListeningPort -Port $legacyPort
    }
}

$legacyDetected = @()
foreach ($legacyPort in $legacyPorts) {
    if (netstat -ano | Select-String ":$legacyPort\s.*LISTENING") {
        $legacyDetected += $legacyPort
    }
}
if ($legacyDetected.Count -gt 0) {
    Write-Host "[WARN] Legacy wrapper MCP ports still listening: $($legacyDetected -join ', ')" -ForegroundColor Yellow
    Write-Host "       These ports are deprecated. Use official stdio MCP servers via mcp_config.json instead." -ForegroundColor Yellow
}

$listenNow = netstat -ano | Select-String ":$($cdar.Port)\s.*LISTENING"
if ($listenNow) {
    Write-Host "[SKIP] $($cdar.Name) already listening on $($cdar.Port)" -ForegroundColor Yellow
    exit 0
}

$scriptPath = Join-Path $ProjectRoot $cdar.Script
if (-not (Test-Path $scriptPath)) {
    Write-Host "[ERROR] Missing script: $scriptPath" -ForegroundColor Red
    exit 1
}

$outLog = Join-Path $logDir "$($cdar.Log).out.log"
$errLog = Join-Path $logDir "$($cdar.Log).err.log"

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""
$env:NO_PROXY = "127.0.0.1,localhost"
$env:MCP_HOST = "127.0.0.1"
$env:MCP_PORT = "$($cdar.Port)"
$env:MCP_PATH = "/sse"
$env:CDAR_PROMPTS_DIR = (Join-Path $ProjectRoot "cdar\prompts_upgrade")

Start-Process -FilePath $FastMcp `
    -ArgumentList @(
        "run",
        ("{0}:mcp" -f $scriptPath),
        "--transport", "sse",
        "--host", "127.0.0.1",
        "--port", "$($cdar.Port)",
        "--path", "/sse",
        "--no-banner"
    ) `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden | Out-Null

Start-Sleep -Seconds 2
$started = netstat -ano | Select-String ":$($cdar.Port)\s.*LISTENING"
if ($started) {
    Write-Host "[OK] $($cdar.Name) started at http://127.0.0.1:$($cdar.Port)/sse" -ForegroundColor Green
} else {
    Write-Host "[FAIL] $($cdar.Name) did not start. Check $errLog" -ForegroundColor Red
    exit 1
}
