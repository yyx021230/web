param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Commit,
    [string]$BuildTime = "unknown",
    [string]$ProjectRoot = "C:\projects\web",
    [string]$BackupRoot = "D:\ztqc-backups\web",
    [string]$ComposeProjectName = ""
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

function Resolve-ComposeProjectName([string]$RequestedName) {
    if ($RequestedName) { return $RequestedName }
    $projects = @()
    $postgresContainers = @(docker ps --filter "label=com.docker.compose.service=postgres" --format "{{.ID}}")
    foreach ($containerId in $postgresContainers) {
        $inspection = @(docker inspect $containerId | ConvertFrom-Json)[0]
        $project = "$($inspection.Config.Labels.'com.docker.compose.project')".Trim()
        if ($project -and $project -notin $projects) { $projects += $project }
    }
    if ($projects.Count -gt 1) {
        throw "Multiple running Compose projects contain PostgreSQL: $($projects -join ', ')"
    }
    if ($projects.Count -eq 1) { return $projects[0] }
    return "web"
}

function Resolve-MountSource([string]$ContainerId, [string]$Destination) {
    if (-not $ContainerId) { return "" }
    $inspection = @(docker inspect $ContainerId | ConvertFrom-Json)[0]
    $mount = @($inspection.Mounts | Where-Object { $_.Destination -eq $Destination } | Select-Object -First 1)
    if ($mount.Count -eq 0) { return "" }
    return "$($mount[0].Source)".Trim()
}

function Read-EnvValue([string]$Path, [string]$Name, [string]$DefaultValue) {
    $line = Get-Content $Path -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -Last 1
    if (-not $line) { return $DefaultValue }
    return (($line -split '=', 2)[1]).Trim().Trim('"').Trim("'")
}

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
$ComposeProjectName = Resolve-ComposeProjectName $ComposeProjectName
$env:COMPOSE_PROJECT_NAME = $ComposeProjectName

Push-Location $ProjectRoot
try {
    $rootComposePath = Join-Path $ProjectRoot "docker-compose.yml"
    $currentPostgresId = "$(docker compose --project-name $ComposeProjectName --env-file $rootEnvPath -f $rootComposePath ps -q postgres)".Trim()
    $currentBackendId = "$(docker compose --project-name $ComposeProjectName --env-file $rootEnvPath -f $rootComposePath ps -q backend)".Trim()
    if (-not $currentPostgresId -or -not $currentBackendId) {
        throw "Unable to resolve the existing production containers for Compose project '$ComposeProjectName'"
    }
    $originalPgMount = Resolve-MountSource $currentPostgresId "/var/lib/postgresql/data"
    $originalUploadsMount = Resolve-MountSource $currentBackendId "/app/uploads"
    if (-not $originalPgMount -or -not $originalUploadsMount) {
        throw "Unable to resolve existing PostgreSQL/uploads mounts; refusing a data-volume blind deployment"
    }

    $databaseUser = "$(docker exec $currentPostgresId printenv POSTGRES_USER | Select-Object -Last 1)".Trim()
    $databaseName = "$(docker exec $currentPostgresId printenv POSTGRES_DB | Select-Object -Last 1)".Trim()
    if (-not $databaseUser -or -not $databaseName) {
        throw "Unable to resolve PostgreSQL credentials from the production container"
    }
    $activeTasksSql = "SELECT count(*) FROM ai_tasks WHERE status IN ('queued','processing');"
    $activeTasksRaw = docker exec $currentPostgresId psql -U $databaseUser -d $databaseName -Atc $activeTasksSql
    if ($LASTEXITCODE -ne 0) { throw "Unable to verify active AI tasks" }
    $activeTasks = [int]($activeTasksRaw | Select-Object -Last 1)
    $otherTasksSql = @"
SELECT
  (SELECT count(*) FROM dify_tasks WHERE status IN ('pending','running'))
  + (SELECT count(*) FROM xhs_account_sync_runs WHERE status IN ('queued','running','cancelling'))
  + (SELECT count(*) FROM xhs_schedule_run_logs WHERE status = 'running' AND started_at >= now() - interval '12 hours');
"@
    $otherTasksRaw = docker exec $currentPostgresId psql -U $databaseUser -d $databaseName -Atc $otherTasksSql
    if ($LASTEXITCODE -ne 0) { throw "Unable to verify active Dify/XHS tasks" }
    $otherActiveTasks = [int]($otherTasksRaw | Select-Object -Last 1)
    $redisId = "$(docker compose --project-name $ComposeProjectName --env-file $rootEnvPath -f $rootComposePath ps -q redis)".Trim()
    $pendingTasks = if ($redisId) { [int](docker exec $redisId redis-cli LLEN ai:image:tasks:pending | Select-Object -Last 1) } else { 0 }
    $processingTasks = if ($redisId) { [int](docker exec $redisId redis-cli LLEN ai:image:tasks:processing | Select-Object -Last 1) } else { 0 }
    if ($activeTasks -gt 0 -or $pendingTasks -gt 0 -or $processingTasks -gt 0 -or $otherActiveTasks -gt 0) {
        throw "Background tasks are still active (ai_database=$activeTasks ai_pending=$pendingTasks ai_processing=$processingTasks dify_xhs=$otherActiveTasks); wait for drain before deployment"
    }

    $pythonImage = Read-EnvValue $rootEnvPath "PYTHON_IMAGE" "python:3.11.13-slim-bookworm"
    $nodeImage = Read-EnvValue $rootEnvPath "NODE_IMAGE" "node:20.19.4-alpine3.22"
    foreach ($baseImage in @($pythonImage, $nodeImage)) {
        docker image inspect $baseImage | Out-Null
        if ($LASTEXITCODE -ne 0) {
            docker pull $baseImage | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Required build base image is unavailable: $baseImage. Load it before deployment; do not stop production services."
            }
        }
    }

    $databaseBytesRaw = docker exec $currentPostgresId psql -U $databaseUser -d $databaseName -Atc "SELECT pg_database_size(current_database());"
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect production database size" }
    $databaseBytes = [int64]($databaseBytesRaw | Select-Object -Last 1)
    $cDrive = Get-PSDrive -Name C
    $dDrive = Get-PSDrive -Name D
    if ($cDrive.Free -lt ($databaseBytes + 8GB)) {
        throw "C drive does not have database-size + 8GB safety headroom for backup/build"
    }
    if ($dDrive.Free -lt 20GB) {
        throw "D drive has less than 20GB free; refusing to create an unverified release backup"
    }

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
    tar -czf $sourceSnapshot --exclude=.git --exclude='.env*' --exclude=.release --exclude=uploads --exclude=runtime --exclude=node_modules --exclude=.next --exclude='._*' -C $ProjectRoot @sourceItems
    if ($LASTEXITCODE -ne 0) { throw "Source snapshot failed" }

    docker compose stop frontend backend ai-worker | Out-Null
    $servicesStopped = $true
    Get-ChildItem $ProjectRoot -Recurse -Force -Filter '._*' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
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

    $newPostgresId = "$(docker compose ps -q postgres)".Trim()
    $newBackendId = "$(docker compose ps -q backend)".Trim()
    $newPgMount = Resolve-MountSource $newPostgresId "/var/lib/postgresql/data"
    $newUploadsMount = Resolve-MountSource $newBackendId "/app/uploads"
    if ($newPgMount -ne $originalPgMount -or $newUploadsMount -ne $originalUploadsMount) {
        throw "Production data mount changed during deployment; refusing to accept the release"
    }

    & (Join-Path $ProjectRoot "scripts\windows\Install-DailyBackup.ps1") -ProjectRoot $ProjectRoot -BackupRoot $BackupRoot
    & (Join-Path $ProjectRoot "scripts\windows\Install-HealthMonitor.ps1") -ProjectRoot $ProjectRoot

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
        docker compose up -d --no-build backend ai-worker frontend
    }
    throw
}
finally {
    Pop-Location
    if (Test-Path $stagingRoot) { Remove-Item -Recurse -Force $stagingRoot }
}
