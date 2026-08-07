param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Commit = "rollback",
    [string]$ProjectRoot = "C:\projects\web",
    [switch]$RestoreUploads,
    [switch]$ConfirmRollback
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRollback) {
    throw "Rollback changes application and database state. Pass -ConfirmRollback."
}

Push-Location $ProjectRoot
try {
    docker compose stop frontend backend ai-worker | Out-Null
    tar -xzf $PackagePath -C $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "Rollback package extraction failed" }
    $env:APP_VERSION = $Version
    $env:GIT_COMMIT = $Commit
    $env:BUILD_TIME = (Get-Date).ToUniversalTime().ToString("o")
    & (Join-Path $ProjectRoot "scripts\windows\Restore-Backup.ps1") -BackupDir $BackupDir -ProjectRoot $ProjectRoot -RestoreUploads:$RestoreUploads -ConfirmRestore
    docker compose up -d --build backend ai-worker frontend
    if ($LASTEXITCODE -ne 0) { throw "Rollback service startup failed" }
    Write-Host "Rollback to $Version completed"
}
finally {
    Pop-Location
}
