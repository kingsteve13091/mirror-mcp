param(
    [ValidateSet("22.22.2", "20.20.2")]
    [string]$Version = "22.22.2"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$ToolsDir = Join-Path $ProjectRoot "tools"
$NodeFolderName = "node-v$Version-win-x64"
$InstallDir = Join-Path $ToolsDir $NodeFolderName
$ZipPath = Join-Path $env:TEMP "$NodeFolderName.zip"
$ChecksumPath = Join-Path $env:TEMP "SHASUMS256.txt"
$NodeZipUrl = "https://nodejs.org/dist/v$Version/$NodeFolderName.zip"
$ChecksumUrl = "https://nodejs.org/dist/v$Version/SHASUMS256.txt"

try {
    chcp 65001 | Out-Null
} catch {
}
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  MCP Mirror - Project Node.js LTS Installer" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target version: v$Version" -ForegroundColor Green
Write-Host "Install path:   $InstallDir" -ForegroundColor Green
Write-Host ""

New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

Write-Host "[1/4] Downloading Node.js ZIP..." -ForegroundColor Yellow
Invoke-WebRequest -Uri $NodeZipUrl -OutFile $ZipPath

Write-Host "[2/4] Verifying checksum..." -ForegroundColor Yellow
Invoke-WebRequest -Uri $ChecksumUrl -OutFile $ChecksumPath
$expectedLine = Select-String -Path $ChecksumPath -Pattern ([regex]::Escape($NodeFolderName + ".zip")) | Select-Object -First 1
if (-not $expectedLine) {
    throw "Unable to find checksum entry for $NodeFolderName.zip"
}
$expectedHash = ($expectedLine.Line -split '\s+')[0].Trim().ToLowerInvariant()
$actualHash = (Get-FileHash -Algorithm SHA256 -Path $ZipPath).Hash.Trim().ToLowerInvariant()
if ($expectedHash -ne $actualHash) {
    throw "Checksum mismatch for downloaded Node.js ZIP."
}

Write-Host "[3/4] Extracting project Node.js runtime..." -ForegroundColor Yellow
if (Test-Path $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
Expand-Archive -Path $ZipPath -DestinationPath $ToolsDir -Force

Write-Host "[4/4] Activating local runtime for this shell..." -ForegroundColor Yellow
. (Join-Path $ProjectRoot "scripts\use_project_node.ps1")
$nodeDir = Use-ProjectNodeLts -ProjectRoot $ProjectRoot
if (-not $nodeDir) {
    throw "Project Node.js runtime was installed but could not be activated."
}

$nodeVersion = (& (Join-Path $nodeDir "node.exe") -v).Trim()
$npmVersion = (& (Join-Path $nodeDir "npm.cmd") -v).Trim()

Write-Host ""
Write-Host "Project Node.js runtime is ready." -ForegroundColor Green
Write-Host "node -v => $nodeVersion" -ForegroundColor Green
Write-Host "npm  -v => $npmVersion" -ForegroundColor Green
