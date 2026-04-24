# Shared helper to prefer a project-local Node.js LTS runtime when available.

function Get-ProjectNodeCandidates {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $directCandidates = @(
        (Join-Path $ProjectRoot "tools\node-lts"),
        (Join-Path $ProjectRoot "tools\node")
    )

    $versionedCandidates = @()
    $toolsDir = Join-Path $ProjectRoot "tools"
    if (Test-Path $toolsDir) {
        $versionedCandidates = Get-ChildItem -Path $toolsDir -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'node-v*-win-x64' } |
            Sort-Object Name -Descending |
            Select-Object -ExpandProperty FullName
    }

    return @($directCandidates + $versionedCandidates)
}

function Get-ProjectNodeDir {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    foreach ($candidate in (Get-ProjectNodeCandidates -ProjectRoot $ProjectRoot)) {
        if (-not $candidate) {
            continue
        }

        $nodeExe = Join-Path $candidate "node.exe"
        if (Test-Path $nodeExe) {
            return $candidate
        }
    }

    return $null
}

function Use-ProjectNodeLts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $nodeDir = Get-ProjectNodeDir -ProjectRoot $ProjectRoot
    if (-not $nodeDir) {
        return $null
    }

    $pathEntries = @($env:Path -split ';') | Where-Object { $_ -and $_.Trim() }
    $filteredEntries = $pathEntries | Where-Object { $_.TrimEnd('\') -ne $nodeDir.TrimEnd('\') }
    $env:Path = (@($nodeDir) + $filteredEntries) -join ';'
    $env:MCP_MIRROR_PROJECT_NODE = $nodeDir

    return $nodeDir
}
