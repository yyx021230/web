param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$BackupRoot = "D:\ztqc-backups\web",
    [string]$MirrorRoot = $env:BACKUP_MIRROR_DIR,
    [int]$RetentionDays = 30
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
        $mountedPath = "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/uploads"}}{{.Source}}{{end}}{{end}}' $backendContainer | Select-Object -Last 1)".Trim()
        if ($LASTEXITCODE -eq 0 -and $mountedPath) { return $mountedPath }
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

    docker compose exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/ztqc-release.dump'
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
    docker cp "${postgresContainer}:/tmp/ztqc-release.dump" $databaseDump
    if ($LASTEXITCODE -ne 0) { throw "docker cp database dump failed" }
    docker compose exec -T postgres pg_restore -l /tmp/ztqc-release.dump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "pg_restore validation failed" }
    docker compose exec -T postgres rm -f /tmp/ztqc-release.dump

    $uploadsPath = Resolve-UploadsPath $ProjectRoot
    if (-not [System.IO.Path]::IsPathRooted($uploadsPath)) {
        $uploadsPath = Join-Path $ProjectRoot $uploadsPath
    }
    if (Test-Path $uploadsPath) {
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
