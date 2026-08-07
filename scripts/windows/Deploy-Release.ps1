param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Commit,
    [string]$BuildTime = "unknown",
    [string]$ProjectRoot = "C:\projects\web",
    [string]$BackupRoot = "D:\ztqc-backups\web"
)

$ErrorActionPreference = "Stop"
$releaseRoot = Join-Path $ProjectRoot ".release"
$stagingRoot = Join-Path $releaseRoot "staging\$Version-$Commit"
$packageRoot = Join-Path $releaseRoot "packages"
$historyPath = Join-Path $releaseRoot "history.ndjson"
$currentPath = Join-Path $releaseRoot "current.json"
$sourceSnapshot = Join-Path $releaseRoot "predeploy-source.tar.gz"
$previousRelease = $null
$backupDir = $null
$servicesStopped = $false

if (Test-Path $currentPath) {
    $previousRelease = Get-Content $currentPath -Raw | ConvertFrom-Json
}

New-Item -ItemType Directory -Force -Path $stagingRoot, $packageRoot | Out-Null
Copy-Item -Force $PackagePath (Join-Path $packageRoot "$Version-$Commit.tar.gz")
tar -xzf $PackagePath -C $stagingRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to extract release package" }

$rootEnvPath = Join-Path $ProjectRoot ".env"
$backendEnvPath = Join-Path $ProjectRoot "backend\.env"
if (-not (Test-Path $rootEnvPath)) { throw "Missing production environment file: $rootEnvPath" }
if (-not (Test-Path $backendEnvPath)) { throw "Missing backend environment file: $backendEnvPath" }
# Compose resolves service env_file relative to the staged compose file. The
# backend .dockerignore excludes this temporary copy from image layers.
Copy-Item -Force $backendEnvPath (Join-Path $stagingRoot "backend\.env")

$env:APP_VERSION = $Version
$env:GIT_COMMIT = $Commit
$env:BUILD_TIME = $BuildTime

Push-Location $ProjectRoot
try {
    docker compose --env-file $rootEnvPath -f (Join-Path $stagingRoot "docker-compose.yml") config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Compose validation failed" }
    docker compose --env-file $rootEnvPath -f (Join-Path $stagingRoot "docker-compose.yml") build backend frontend
    if ($LASTEXITCODE -ne 0) { throw "Release image build failed" }

    $backupScript = Join-Path $ProjectRoot "scripts\windows\Backup-Release.ps1"
    $backupDir = & $backupScript -ProjectRoot $ProjectRoot -BackupRoot $BackupRoot
    if (-not $backupDir) { throw "Backup did not return a path" }

    if (Test-Path $sourceSnapshot) { Remove-Item -Force $sourceSnapshot }
    $sourceItems = @("backend", "frontend", "scripts", "docker-compose.yml", "docker-compose.dev.yml") |
        Where-Object { Test-Path (Join-Path $ProjectRoot $_) }
    tar -czf $sourceSnapshot --exclude=.git --exclude='.env*' --exclude=.release --exclude=uploads --exclude=runtime --exclude=node_modules --exclude=.next -C $ProjectRoot @sourceItems
    if ($LASTEXITCODE -ne 0) { throw "Source snapshot failed" }

    docker compose stop frontend backend ai-worker | Out-Null
    $servicesStopped = $true
    tar -xzf $PackagePath -C $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "Release extraction failed" }

    docker compose run --rm backend alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed" }
    docker compose up -d backend ai-worker frontend
    if ($LASTEXITCODE -ne 0) { throw "Service startup failed" }

    $deadline = (Get-Date).AddMinutes(3)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 8
            $front = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3000/" -TimeoutSec 8
            if ($ready.status -eq "ready" -and $front.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch { Start-Sleep -Seconds 5 }
    }
    if (-not $healthy) { throw "Release health check failed" }

    $release = [ordered]@{
        version = $Version
        commit = $Commit
        buildTime = $BuildTime
        deployedAt = (Get-Date).ToUniversalTime().ToString("o")
        backupDir = $backupDir
        package = (Join-Path $packageRoot "$Version-$Commit.tar.gz")
    }
    $releaseJson = $release | ConvertTo-Json -Depth 6
    $releaseJson | Set-Content -Encoding UTF8 $currentPath
    ($release | ConvertTo-Json -Compress) | Add-Content -Encoding UTF8 $historyPath
    Write-Host "Release $Version ($Commit) deployed successfully"
}
catch {
    Write-Error "Deployment failed: $($_.Exception.Message)"
    if ($servicesStopped -and $backupDir -and (Test-Path $sourceSnapshot)) {
        Write-Warning "Restoring previous source and database backup..."
        tar -xzf $sourceSnapshot -C $ProjectRoot
        if ($previousRelease) {
            $env:APP_VERSION = $previousRelease.version
            $env:GIT_COMMIT = $previousRelease.commit
            $env:BUILD_TIME = $previousRelease.buildTime
        }
        & (Join-Path $ProjectRoot "scripts\windows\Restore-Backup.ps1") -BackupDir $backupDir -ProjectRoot $ProjectRoot -ConfirmRestore
        docker compose up -d --build backend ai-worker frontend
    }
    throw
}
finally {
    Pop-Location
    if (Test-Path $stagingRoot) { Remove-Item -Recurse -Force $stagingRoot }
}
