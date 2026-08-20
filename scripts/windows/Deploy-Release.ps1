param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Commit,
    [string]$BuildTime = "unknown",
    [string]$ProjectRoot = "C:\projects\web",
    [string]$BackupRoot = "D:\ztqc-backups\web",
    [string]$ExistingBackupDir = "",
    [string]$ComposeProjectName = "",
    [switch]$InstallDailyBackup
)

$ErrorActionPreference = "Stop"
$releaseRoot = Join-Path $ProjectRoot ".release"
$stagingRoot = Join-Path $releaseRoot "staging\$Version-$Commit"
$packageRoot = Join-Path $releaseRoot "packages"
$historyPath = Join-Path $releaseRoot "history.ndjson"
$currentPath = Join-Path $releaseRoot "current.json"
$sourceSnapshot = Join-Path $releaseRoot "predeploy-source.tar.gz"
$rollbackRestoreScript = Join-Path $releaseRoot "rollback-Restore-Backup.ps1"
$previousRelease = $null
$backupDir = $null
$servicesStopped = $false
$originalBackendImageId = ""
$originalFrontendImageId = ""
$candidateBackendImage = ""
$candidateFrontendImage = ""
$migrationAttempted = $false
$preMigrationRevision = ""
$originalAppVersion = ""
$originalGitCommit = ""
$originalBuildTime = ""

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

function Resolve-ContainerImage([string]$ContainerId) {
    if (-not $ContainerId) { return "" }
    $inspection = @(docker inspect $ContainerId | ConvertFrom-Json)[0]
    return "$($inspection.Config.Image)".Trim()
}

function Read-ContainerEnvValue([string]$ContainerId, [string]$Name, [string]$DefaultValue) {
    if (-not $ContainerId) { return $DefaultValue }
    $inspection = @(docker inspect $ContainerId | ConvertFrom-Json)[0]
    $prefix = "${Name}="
    $entry = @($inspection.Config.Env | Where-Object { $_.StartsWith($prefix) } | Select-Object -Last 1)
    if ($entry.Count -eq 0) { return $DefaultValue }
    return "$($entry[0].Substring($prefix.Length))".Trim()
}

function Assert-ExistingBackup([string]$Path, [string]$PostgresImage) {
    if (-not (Test-Path $Path -PathType Container)) {
        throw "Existing backup directory does not exist: $Path"
    }
    $manifestPath = Join-Path $Path "manifest.json"
    $databaseDump = Join-Path $Path "postgres.dump"
    if (-not (Test-Path $manifestPath -PathType Leaf) -or -not (Test-Path $databaseDump -PathType Leaf)) {
        throw "Existing backup is missing manifest.json or postgres.dump: $Path"
    }
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ([int64]$manifest.databaseBytes -ne (Get-Item $databaseDump).Length) {
        throw "Existing backup database size does not match its manifest"
    }
    if ($manifest.uploadsArchive) {
        $uploadsArchive = Join-Path $Path "$($manifest.uploadsArchive)"
        if (-not (Test-Path $uploadsArchive -PathType Leaf) -or [int64]$manifest.uploadsBytes -ne (Get-Item $uploadsArchive).Length) {
            throw "Existing backup uploads archive does not match its manifest"
        }
    }
    docker run --rm `
        --mount "type=bind,source=$Path,target=/backup,readonly" `
        $PostgresImage `
        pg_restore -l /backup/postgres.dump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Existing backup pg_restore validation failed" }
}

function Read-EnvValue([string]$Path, [string]$Name, [string]$DefaultValue) {
    $line = Get-Content $Path -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -Last 1
    if (-not $line) { return $DefaultValue }
    return (($line -split '=', 2)[1]).Trim().Trim('"').Trim("'")
}

function Assert-BackgroundQueuesDrained(
    [string]$PostgresId,
    [string]$DatabaseUser,
    [string]$DatabaseName,
    [string]$RedisId,
    [string]$Phase
) {
    $activeTasksSql = "SELECT count(*) FROM ai_tasks WHERE status IN ('queued','processing');"
    $activeTasksRaw = docker exec $PostgresId psql -U $DatabaseUser -d $DatabaseName -Atc $activeTasksSql
    if ($LASTEXITCODE -ne 0) { throw "Unable to verify active AI tasks during $Phase" }
    $activeTasks = [int]($activeTasksRaw | Select-Object -Last 1)
    $otherTasksSql = @"
SELECT
  (SELECT count(*) FROM dify_tasks WHERE status IN ('pending','running'))
  + (SELECT count(*) FROM xhs_account_sync_runs WHERE status IN ('queued','running','cancelling'))
  + (SELECT count(*) FROM xhs_schedule_run_logs WHERE status = 'running' AND started_at >= now() - interval '12 hours');
"@
    $otherTasksRaw = docker exec $PostgresId psql -U $DatabaseUser -d $DatabaseName -Atc $otherTasksSql
    if ($LASTEXITCODE -ne 0) { throw "Unable to verify active Dify/XHS tasks during $Phase" }
    $otherActiveTasks = [int]($otherTasksRaw | Select-Object -Last 1)
    $pendingTasks = if ($RedisId) { [int](docker exec $RedisId redis-cli LLEN ai:image:tasks:pending | Select-Object -Last 1) } else { 0 }
    $processingTasks = if ($RedisId) { [int](docker exec $RedisId redis-cli LLEN ai:image:tasks:processing | Select-Object -Last 1) } else { 0 }
    if ($activeTasks -gt 0 -or $pendingTasks -gt 0 -or $processingTasks -gt 0 -or $otherActiveTasks -gt 0) {
        throw "Background tasks are active during $Phase (ai_database=$activeTasks ai_pending=$pendingTasks ai_processing=$processingTasks dify_xhs=$otherActiveTasks)"
    }
}

if (Test-Path $currentPath) {
    $previousRelease = Get-Content $currentPath -Raw | ConvertFrom-Json
}

New-Item -ItemType Directory -Force -Path $stagingRoot, $packageRoot | Out-Null
Copy-Item -Force (Join-Path $ProjectRoot "scripts\windows\Restore-Backup.ps1") $rollbackRestoreScript
Copy-Item -Force $PackagePath (Join-Path $packageRoot "$Version-$Commit.tar.gz")
tar -xzf $PackagePath -C $stagingRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to extract release package" }
Get-ChildItem $stagingRoot -Recurse -Force -Filter '._*' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction Stop

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
    $currentRedisId = "$(docker compose --project-name $ComposeProjectName --env-file $rootEnvPath -f $rootComposePath ps -q redis)".Trim()
    $currentMinioId = "$(docker compose --project-name $ComposeProjectName --env-file $rootEnvPath -f $rootComposePath ps -q minio)".Trim()
    if (-not $currentPostgresId -or -not $currentBackendId -or -not $currentRedisId -or -not $currentMinioId) {
        throw "Unable to resolve the existing production containers for Compose project '$ComposeProjectName'"
    }
    $originalPgMount = Resolve-MountSource $currentPostgresId "/var/lib/postgresql/data"
    $originalUploadsMount = Resolve-MountSource $currentBackendId "/app/uploads"
    if (-not $originalPgMount -or -not $originalUploadsMount) {
        throw "Unable to resolve existing PostgreSQL/uploads mounts; refusing a data-volume blind deployment"
    }
    $originalBackendImageId = "$(docker inspect --format '{{.Image}}' $currentBackendId)".Trim()
    $currentFrontendId = "$(docker compose --project-name $ComposeProjectName --env-file $rootEnvPath -f $rootComposePath ps -q frontend)".Trim()
    $originalFrontendImageId = if ($currentFrontendId) { "$(docker inspect --format '{{.Image}}' $currentFrontendId)".Trim() } else { "" }
    if (-not $originalBackendImageId -or -not $originalFrontendImageId) {
        throw "Unable to preserve current backend/frontend image IDs for automatic rollback"
    }
    $originalAppVersion = Read-ContainerEnvValue $currentBackendId "APP_VERSION" "unknown"
    $originalGitCommit = Read-ContainerEnvValue $currentBackendId "GIT_COMMIT" "unknown"
    $originalBuildTime = Read-ContainerEnvValue $currentBackendId "BUILD_TIME" "unknown"

    # Application-only releases must not upgrade, pull, or recreate stateful
    # infrastructure. Preserve the exact image references already in service.
    $env:POSTGRES_IMAGE = Resolve-ContainerImage $currentPostgresId
    $env:REDIS_IMAGE = Resolve-ContainerImage $currentRedisId
    $env:MINIO_IMAGE = Resolve-ContainerImage $currentMinioId
    if (-not $env:POSTGRES_IMAGE -or -not $env:REDIS_IMAGE -or -not $env:MINIO_IMAGE) {
        throw "Unable to preserve current PostgreSQL/Redis/MinIO image references"
    }

    $databaseUser = "$(docker exec $currentPostgresId printenv POSTGRES_USER | Select-Object -Last 1)".Trim()
    $databaseName = "$(docker exec $currentPostgresId printenv POSTGRES_DB | Select-Object -Last 1)".Trim()
    if (-not $databaseUser -or -not $databaseName) {
        throw "Unable to resolve PostgreSQL credentials from the production container"
    }
    $preMigrationRevision = "$(docker exec $currentPostgresId psql -U $databaseUser -d $databaseName -Atc 'SELECT version_num FROM alembic_version LIMIT 1;' | Select-Object -Last 1)".Trim()
    if ($LASTEXITCODE -ne 0 -or -not $preMigrationRevision) {
        throw "Unable to resolve the production Alembic revision"
    }
    $redisId = $currentRedisId
    Assert-BackgroundQueuesDrained $currentPostgresId $databaseUser $databaseName $redisId "initial preflight"

    $pythonImage = Read-EnvValue $rootEnvPath "PYTHON_IMAGE" "python:3.11.13-slim-bookworm"
    $nodeImage = Read-EnvValue $rootEnvPath "NODE_IMAGE" "node:20.19.4-alpine3.22"
    $appImagePrefix = Read-EnvValue $rootEnvPath "APP_IMAGE_PREFIX" "ztqc"
    $candidateBackendImage = "${appImagePrefix}/backend:${Version}"
    $candidateFrontendImage = "${appImagePrefix}/frontend:${Version}"
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
    docker run --rm --entrypoint python $candidateBackendImage -m compileall -q -f /app/app
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate backend image contains invalid Python source"
    }

    Assert-BackgroundQueuesDrained $currentPostgresId $databaseUser $databaseName $redisId "post-build preflight"

    if (Test-Path $sourceSnapshot) { Remove-Item -Force $sourceSnapshot }
    $sourceItems = @("backend", "frontend", "scripts", "docker-compose.yml", "docker-compose.dev.yml") |
        Where-Object { Test-Path (Join-Path $ProjectRoot $_) }
    tar -czf $sourceSnapshot `
        --exclude=.git `
        --exclude='.env*' `
        --exclude=.release `
        --exclude=uploads `
        --exclude=runtime `
        --exclude=node_modules `
        --exclude=.next `
        --exclude=.venv `
        --exclude=__pycache__ `
        --exclude=.pytest_cache `
        --exclude=.mypy_cache `
        --exclude='*.db' `
        --exclude='*.db-*' `
        --exclude=db_backups `
        --exclude=backups `
        --exclude='._*' `
        -C $ProjectRoot @sourceItems
    if ($LASTEXITCODE -ne 0) { throw "Source snapshot failed" }

    # Close the user entrypoint first, then make sure no task entered during the
    # image build before stopping the API and worker processes.
    docker compose stop frontend | Out-Null
    $servicesStopped = $true
    Assert-BackgroundQueuesDrained $currentPostgresId $databaseUser $databaseName $redisId "frontend-closed preflight"
    docker compose stop backend ai-worker | Out-Null
    Assert-BackgroundQueuesDrained $currentPostgresId $databaseUser $databaseName $redisId "application-stopped preflight"

    if ($ExistingBackupDir) {
        Assert-ExistingBackup $ExistingBackupDir $env:POSTGRES_IMAGE
        $backupDir = $ExistingBackupDir
    } else {
        $backupScript = Join-Path $ProjectRoot "scripts\windows\Backup-Release.ps1"
        # The daily job keeps a full uploads archive. Releases only mutate code
        # and schema, so avoid extending downtime by recompressing immutable files.
        $backupDir = & $backupScript -ProjectRoot $ProjectRoot -BackupRoot $BackupRoot -SkipUploads
    }
    if (-not $backupDir) { throw "Backup did not return a path" }

    Get-ChildItem $ProjectRoot -Force -Filter '._*' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    @("backend", "frontend", "scripts") | ForEach-Object {
        Get-ChildItem (Join-Path $ProjectRoot $_) -Recurse -Force -Filter '._*' -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
    tar -xzf $PackagePath -C $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "Release extraction failed" }
    Get-ChildItem $ProjectRoot -Force -Filter '._*' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction Stop
    @("backend", "frontend", "scripts") | ForEach-Object {
        Get-ChildItem (Join-Path $ProjectRoot $_) -Recurse -Force -Filter '._*' -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction Stop
    }

    $migrationAttempted = $true
    docker compose run --rm --no-deps backend alembic upgrade head
    $migrationExitCode = $LASTEXITCODE
    $observedMigrationRevision = "$(docker exec $currentPostgresId psql -U $databaseUser -d $databaseName -Atc 'SELECT version_num FROM alembic_version LIMIT 1;' | Select-Object -Last 1)".Trim()
    if ($LASTEXITCODE -ne 0 -or -not $observedMigrationRevision) {
        throw "Unable to verify the post-migration Alembic revision"
    }
    # Only restore the database when its revision actually changed. Syntax or
    # startup failures before the first migration must not replay an older dump.
    $migrationAttempted = $observedMigrationRevision -ne $preMigrationRevision
    if ($migrationExitCode -ne 0) { throw "Database migration failed" }
    $postMigrationRevision = $observedMigrationRevision
    docker compose up -d --no-deps backend ai-worker frontend
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

    if ($InstallDailyBackup) {
        & (Join-Path $ProjectRoot "scripts\windows\Install-DailyBackup.ps1") -ProjectRoot $ProjectRoot -BackupRoot $BackupRoot
    }
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
    $deploymentError = $_.Exception.Message
    $rollbackErrors = [System.Collections.Generic.List[string]]::new()
    Write-Warning "Deployment failed: $deploymentError"
    if ($servicesStopped) {
        Write-Warning "Restoring previous source, images, and database state..."
        if (Test-Path $sourceSnapshot) {
            try {
                tar -xzf $sourceSnapshot -C $ProjectRoot
                if ($LASTEXITCODE -ne 0) { throw "source snapshot extraction failed" }
            } catch {
                $rollbackErrors.Add("source: $($_.Exception.Message)")
            }
        }
        if ($previousRelease) {
            $env:APP_VERSION = $previousRelease.version
            $env:GIT_COMMIT = $previousRelease.commit
            $env:BUILD_TIME = $previousRelease.buildTime
        } else {
            # Legacy deployments may not expose release metadata. The old image
            # IDs are retagged to the candidate tags below, so keep that tag
            # instead of attempting to pull an invalid ':unknown' image.
            $env:APP_VERSION = if ($originalAppVersion -and $originalAppVersion -ne "unknown") { $originalAppVersion } else { $Version }
            $env:GIT_COMMIT = $originalGitCommit
            $env:BUILD_TIME = $originalBuildTime
        }
        if ($backupDir -and $migrationAttempted) {
            try {
                & $rollbackRestoreScript -BackupDir $backupDir -ProjectRoot $ProjectRoot -ConfirmRestore
            } catch {
                $rollbackErrors.Add("database: $($_.Exception.Message)")
            }
        }
        try {
            if ($originalBackendImageId -and $candidateBackendImage) {
                docker tag $originalBackendImageId $candidateBackendImage
            }
            if ($originalFrontendImageId -and $candidateFrontendImage) {
                docker tag $originalFrontendImageId $candidateFrontendImage
            }
            docker compose up -d --no-build --no-deps backend ai-worker frontend
            if ($LASTEXITCODE -ne 0) { throw "old application containers failed to start" }
        } catch {
            $rollbackErrors.Add("application: $($_.Exception.Message)")
        }
    }
    if ($rollbackErrors.Count -gt 0) {
        throw "Deployment failed: $deploymentError. Rollback issues: $($rollbackErrors -join '; ')"
    }
    throw "Deployment failed: $deploymentError. Previous release restored."
}
finally {
    Pop-Location
    if (Test-Path $stagingRoot) { Remove-Item -Recurse -Force $stagingRoot }
}
