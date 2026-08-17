param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$BackupRoot = "D:\ztqc-backups\web",
    [string]$MirrorRoot = $env:BACKUP_MIRROR_DIR,
    [int]$RetentionDays = 30,
    [switch]$SkipUploads
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $BackupRoot $timestamp
$databaseDump = Join-Path $backupDir "postgres.dump"
$uploadsArchive = Join-Path $backupDir "uploads.tar.gz"
$manifestPath = Join-Path $backupDir "manifest.json"

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

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
Push-Location $ProjectRoot
try {
    $postgresContainer = (docker compose ps -q postgres).Trim()
    if (-not $postgresContainer) {
        throw "PostgreSQL container is not running"
    }
    $databaseUser = "$(docker exec $postgresContainer printenv POSTGRES_USER | Select-Object -Last 1)".Trim()
    $databaseName = "$(docker exec $postgresContainer printenv POSTGRES_DB | Select-Object -Last 1)".Trim()
    $databasePassword = "$(docker exec $postgresContainer printenv POSTGRES_PASSWORD | Select-Object -Last 1)".Trim()
    $postgresImage = "$(docker inspect --format '{{.Config.Image}}' $postgresContainer)".Trim()
    if (-not $databaseUser -or -not $databaseName -or -not $databasePassword -or -not $postgresImage) {
        throw "Unable to resolve PostgreSQL backup credentials from the container"
    }

    # Write the dump directly to the D-drive backup directory. Keeping a full
    # temporary dump in the PostgreSQL container would consume Docker's C drive.
    docker run --rm `
        --network "container:$postgresContainer" `
        --mount "type=bind,source=$backupDir,target=/backup" `
        -e "PGPASSWORD=$databasePassword" `
        $postgresImage `
        pg_dump -h 127.0.0.1 -U $databaseUser -d $databaseName -Fc -f /backup/postgres.dump
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
    docker run --rm `
        --mount "type=bind,source=$backupDir,target=/backup,readonly" `
        $postgresImage `
        pg_restore -l /backup/postgres.dump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "pg_restore validation failed" }

    $uploadsPath = Resolve-UploadsPath $ProjectRoot
    if (-not [System.IO.Path]::IsPathRooted($uploadsPath)) {
        $uploadsPath = Join-Path $ProjectRoot $uploadsPath
    }
    if (-not $SkipUploads -and (Test-Path $uploadsPath)) {
        tar -czf $uploadsArchive -C $uploadsPath .
        if ($LASTEXITCODE -ne 0) { throw "uploads backup failed" }
    }

    $releaseFile = Join-Path $ProjectRoot ".release\current.json"
    $release = $null
    if (Test-Path $releaseFile) {
        $release = Get-Content $releaseFile -Raw | ConvertFrom-Json
    }
    $manifest = [ordered]@{
        createdAt = (Get-Date).ToUniversalTime().ToString("o")
        projectRoot = $ProjectRoot
        databaseDump = "postgres.dump"
        databaseBytes = (Get-Item $databaseDump).Length
        uploadsArchive = if (Test-Path $uploadsArchive) { "uploads.tar.gz" } else { $null }
        uploadsBytes = if (Test-Path $uploadsArchive) { (Get-Item $uploadsArchive).Length } else { 0 }
        release = $release
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $manifestPath

    if ($MirrorRoot) {
        New-Item -ItemType Directory -Force -Path $MirrorRoot | Out-Null
        Copy-Item -Recurse -Force $backupDir (Join-Path $MirrorRoot $timestamp)
    }

    if ($RetentionDays -gt 0) {
        $cutoff = (Get-Date).AddDays(-$RetentionDays)
        Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d{8}_\d{6}$' -and $_.LastWriteTime -lt $cutoff } |
            Remove-Item -Recurse -Force
    }

    Write-Output $backupDir
}
finally {
    Pop-Location
}
