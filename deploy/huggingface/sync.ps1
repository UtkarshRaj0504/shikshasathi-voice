[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SpaceRemote
)

$ErrorActionPreference = "Stop"

if ($SpaceRemote -match "^https?://[^/]*@" -or $SpaceRemote -match "(?i)[?&](token|access_token)=") {
    throw "Do not embed credentials in the remote URL. Authenticate with the Hugging Face CLI or Git credential manager."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendRoot = Join-Path $RepoRoot "backend"
$WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("shikshasathi-space-" + [guid]::NewGuid().ToString("N"))
$BundleRoot = Join-Path $WorkRoot "bundle"
$SpaceRoot = Join-Path $WorkRoot "space"

function Copy-CleanTree([string]$Source, [string]$Destination) {
    Get-ChildItem -LiteralPath $Source -Force -Recurse | ForEach-Object {
        $relative = [System.IO.Path]::GetRelativePath($Source, $_.FullName)
        $parts = $relative -split "[\\/]"
        if ($parts | Where-Object {
            $_ -eq ".git" -or $_ -eq ".venv" -or $_ -eq "__pycache__" -or
            $_ -ieq ".env" -or $_.StartsWith(".env.", [System.StringComparison]::OrdinalIgnoreCase)
        }) {
            return
        }

        $target = Join-Path $Destination $relative
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Path $target -Force | Out-Null
        } else {
            $targetParent = Split-Path -Parent $target
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}

try {
    Copy-CleanTree (Join-Path $BackendRoot "app") (Join-Path $BundleRoot "backend/app")
    Copy-CleanTree (Join-Path $BackendRoot "alembic") (Join-Path $BundleRoot "backend/alembic")
    New-Item -ItemType Directory -Path (Join-Path $BundleRoot "backend") -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $BackendRoot "alembic.ini") -Destination (Join-Path $BundleRoot "backend/alembic.ini")
    Copy-Item -Path (Join-Path $RepoRoot "requirements.txt") -Destination $BundleRoot
    Copy-Item -Path (Join-Path $PSScriptRoot "Dockerfile") -Destination (Join-Path $BundleRoot "Dockerfile")
    Copy-Item -Path (Join-Path $PSScriptRoot "README.md") -Destination (Join-Path $BundleRoot "README.md")
    Copy-Item -Path (Join-Path $PSScriptRoot "start.sh") -Destination (Join-Path $BundleRoot "start.sh")

    & git clone --quiet $SpaceRemote $SpaceRoot 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not clone the Space. Check its remote URL and authenticate with the Hugging Face CLI or Git credential manager."
    }

    Copy-Item -Path (Join-Path $BundleRoot "*") -Destination $SpaceRoot -Recurse -Force
    & git -C $SpaceRoot add -- Dockerfile README.md start.sh requirements.txt backend
    if ($LASTEXITCODE -ne 0) {
        throw "Could not stage the assembled backend deployment."
    }

    & git -C $SpaceRoot diff --cached --quiet
    if ($LASTEXITCODE -eq 1) {
        & git -C $SpaceRoot commit -m "Deploy ShikshaSaathi Voice backend"
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the deployment commit. Check that Git author identity is configured."
        }
    } elseif ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the staged deployment."
    }

    & git -C $SpaceRoot push origin HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "Could not push to the Space. Check authentication and Space write access."
    }

    Write-Host "Backend deployment pushed successfully."
}
finally {
    if (Test-Path -LiteralPath $WorkRoot) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
}
