param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [string]$ProjectRoot = "C:\projects\web",
    [switch]$RestoreUploads,
    [switch]$StartServices,
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "Restore is destructive. Pass -ConfirmRestore to continue."
}

$databaseDump = Join-Path $BackupDir "postgres.dump"
if (-not (Test-Path $databaseDump)) {
    throw "Missing database backup: $databaseDump"
}

function Resolve-UploadsPath([string]$Root) {
    if ($env:UPLOADS_HOST_PATH) { return $env:UPLOADS_HOST_PATH }

    $backendContainer = "$(docker compose ps --all -q backend | Select-Object -Last 1)".Trim()
    if ($backendContainer) {
        $inspection = @(docker inspect $backendContainer | ConvertFrom-Json)[0]
        $mount = @($inspection.Mounts | Where-Object { $_.Destination -eq "/app/uploads" } | Select-Object -First 1)
        if ($mount.Count -gt 0 -and $mount[0].Source) { return "$($mount[0].Source)".Trim() }
    }

    $rootEnv = Join-Path $Root ".env"
    if (Test-Path $rootEnv) {
        $uploadsLine = Get-Content $rootEnv |
            Where-Object { $_ -match '^\s*UPLOADS_HOST_PATH\s*=' } |
            Select-Object -Last 1
        if ($uploadsLine) {
            return (($uploadsLine -split '=', 2)[1]).Trim().Trim('"').Trim("'")
        }
    }
    return (Join-Path $Root "uploads")
}

Push-Location $ProjectRoot
try {
    docker compose stop frontend backend ai-worker | Out-Null
    docker compose up -d postgres | Out-Null
    $postgresContainer = (docker compose ps -q postgres).Trim()
    if (-not $postgresContainer) { throw "PostgreSQL container is unavailable" }

    docker cp $databaseDump "${postgresContainer}:/tmp/ztqc-restore.dump"
    if ($LASTEXITCODE -ne 0) { throw "docker cp restore dump failed" }
    $databaseUser = (docker compose exec -T postgres printenv POSTGRES_USER | Select-Object -Last 1).Trim()
    $databaseName = (docker compose exec -T postgres printenv POSTGRES_DB | Select-Object -Last 1).Trim()
    if (-not $databaseUser -or -not $databaseName) {
        throw "Unable to resolve PostgreSQL restore credentials from the container"
    }

    $terminateSql = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$databaseName' AND pid <> pg_backend_pid();"
    docker compose exec -T postgres psql -U $databaseUser -d postgres -v ON_ERROR_STOP=1 -c $terminateSql | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "failed to terminate active database sessions" }
    docker compose exec -T postgres dropdb -U $databaseUser --if-exists $databaseName
    if ($LASTEXITCODE -ne 0) { throw "failed to drop the target database" }
    docker compose exec -T postgres createdb -U $databaseUser $databaseName
    if ($LASTEXITCODE -ne 0) { throw "failed to recreate the target database" }
    docker compose exec -T postgres pg_restore -U $databaseUser -d $databaseName --no-owner --no-acl /tmp/ztqc-restore.dump
    if ($LASTEXITCODE -ne 0) { throw "database restore failed" }
    docker compose exec -T postgres rm -f /tmp/ztqc-restore.dump

    if ($RestoreUploads) {
        $uploadsArchive = Join-Path $BackupDir "uploads.tar.gz"
        if (Test-Path $uploadsArchive) {
            $uploadsPath = Resolve-UploadsPath $ProjectRoot
            if (-not [System.IO.Path]::IsPathRooted($uploadsPath)) {
                $uploadsPath = Join-Path $ProjectRoot $uploadsPath
            }
            $quarantine = "${uploadsPath}.before-restore.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
            if (Test-Path $uploadsPath) { Move-Item $uploadsPath $quarantine }
            New-Item -ItemType Directory -Force -Path $uploadsPath | Out-Null
            tar -xzf $uploadsArchive -C $uploadsPath
            if ($LASTEXITCODE -ne 0) { throw "uploads restore failed" }
        }
    }

    if ($StartServices) {
        docker compose up -d backend ai-worker frontend | Out-Null
    }
}
finally {
    Pop-Location
}
