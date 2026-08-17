param(
    [string]$ProjectRoot = "C:\projects\web",
    [int]$DiskWarningPercent = 85,
    [int]$DiskCriticalPercent = 93,
    [int]$DatabaseConnectionWarning = 120,
    [int]$QueueWarning = 100,
    [string]$BackupRoot = "D:\ztqc-backups\web",
    [int]$BackupMaxAgeHours = 30,
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$checks = New-Object System.Collections.Generic.List[object]
$critical = $false

function Add-Check([string]$Name, [string]$Status, [object]$Value, [string]$Message) {
    $script:checks.Add([ordered]@{ name = $Name; status = $Status; value = $Value; message = $Message })
    if ($Status -eq "critical") { $script:critical = $true }
}

Push-Location $ProjectRoot
try {
    foreach ($driveName in @("C", "D")) {
        $drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
        if ($drive -and (($drive.Used + $drive.Free) -gt 0)) {
            $usedPercent = [math]::Round(100 * $drive.Used / ($drive.Used + $drive.Free), 1)
            $status = if ($usedPercent -ge $DiskCriticalPercent) { "critical" } elseif ($usedPercent -ge $DiskWarningPercent) { "warning" } else { "ok" }
            if ($driveName -eq "C" -and $drive.Free -lt 20GB) { $status = "critical" }
            elseif ($driveName -eq "C" -and $drive.Free -lt 35GB -and $status -eq "ok") { $status = "warning" }
            Add-Check "disk_$driveName" $status $usedPercent "Disk ${driveName}: ${usedPercent}% used"
        }
    }

    try {
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 8
        Add-Check "backend_ready" "ok" $ready.status "Backend readiness passed"
    } catch {
        Add-Check "backend_ready" "critical" $null $_.Exception.Message
    }

    try {
        $frontend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3000/" -TimeoutSec 8
        Add-Check "frontend" "ok" $frontend.StatusCode "Frontend responded"
    } catch {
        Add-Check "frontend" "critical" $null $_.Exception.Message
    }

    try {
        $postgresContainer = "$(docker compose ps -q postgres | Select-Object -Last 1)".Trim()
        if (-not $postgresContainer) { throw "PostgreSQL container is not running" }
        $databaseUser = "$(docker exec $postgresContainer printenv POSTGRES_USER | Select-Object -Last 1)".Trim()
        $databaseName = "$(docker exec $postgresContainer printenv POSTGRES_DB | Select-Object -Last 1)".Trim()
        if (-not $databaseUser -or -not $databaseName) { throw "Unable to resolve PostgreSQL health-check credentials" }
        $connectionsRaw = docker exec $postgresContainer psql -U $databaseUser -d $databaseName -Atc "SELECT count(*) FROM pg_stat_activity;"
        if ($LASTEXITCODE -ne 0) { throw "PostgreSQL connection query failed" }
        $connections = [int]($connectionsRaw | Select-Object -Last 1)
        $status = if ($connections -ge $DatabaseConnectionWarning) { "warning" } else { "ok" }
        Add-Check "database_connections" $status $connections "PostgreSQL active connections"
    } catch {
        Add-Check "database_connections" "critical" $null $_.Exception.Message
    }

    try {
        $activeTasksRaw = docker exec $postgresContainer psql -U $databaseUser -d $databaseName -Atc "SELECT count(*) FROM ai_tasks WHERE status IN ('queued','processing');"
        if ($LASTEXITCODE -ne 0) { throw "AI active-task query failed" }
        $activeTasks = [int]($activeTasksRaw | Select-Object -Last 1)
        Add-Check "ai_active_tasks" "ok" $activeTasks "Database queued/processing AI tasks"
    } catch {
        Add-Check "ai_active_tasks" "critical" $null $_.Exception.Message
    }

    try {
        $otherTasksSql = @"
SELECT
  (SELECT count(*) FROM dify_tasks WHERE status IN ('pending','running'))
  + (SELECT count(*) FROM xhs_account_sync_runs WHERE status IN ('queued','running','cancelling'))
  + (SELECT count(*) FROM xhs_schedule_run_logs WHERE status = 'running' AND started_at >= now() - interval '12 hours');
"@
        $otherTasksRaw = docker exec $postgresContainer psql -U $databaseUser -d $databaseName -Atc $otherTasksSql
        if ($LASTEXITCODE -ne 0) { throw "Dify/XHS active-task query failed" }
        $otherTasks = [int]($otherTasksRaw | Select-Object -Last 1)
        Add-Check "dify_xhs_active_tasks" "ok" $otherTasks "Database queued/running Dify and XHS tasks"
    } catch {
        Add-Check "dify_xhs_active_tasks" "critical" $null $_.Exception.Message
    }

    foreach ($queue in @("ai:image:tasks:pending", "ai:image:tasks:processing")) {
        try {
            $depthRaw = docker compose exec -T redis redis-cli LLEN $queue
            if ($LASTEXITCODE -ne 0) { throw "Redis queue query failed: $queue" }
            $depth = [int]($depthRaw | Select-Object -Last 1)
            $status = if ($depth -ge $QueueWarning) { "warning" } else { "ok" }
            Add-Check "redis_$queue" $status $depth "Redis queue depth"
        } catch {
            Add-Check "redis_$queue" "critical" $null $_.Exception.Message
        }
    }

    $latestBackup = Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d{8}_\d{6}$' } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latestBackup) {
        Add-Check "backup_age" "critical" $null "No valid backup directory found"
    } else {
        $backupAgeHours = [math]::Round(((Get-Date) - $latestBackup.LastWriteTime).TotalHours, 1)
        $manifestExists = Test-Path (Join-Path $latestBackup.FullName "manifest.json")
        $dumpExists = Test-Path (Join-Path $latestBackup.FullName "postgres.dump")
        $backupStatus = if (-not $manifestExists -or -not $dumpExists -or $backupAgeHours -gt $BackupMaxAgeHours) { "critical" } else { "ok" }
        Add-Check "backup_age" $backupStatus $backupAgeHours "Latest validated backup age in hours"
    }

    $result = [ordered]@{
        checkedAt = (Get-Date).ToUniversalTime().ToString("o")
        status = if ($critical) { "critical" } elseif ($checks.status -contains "warning") { "warning" } else { "ok" }
        checks = $checks
    }
    if (-not $OutputPath) {
        $OutputPath = Join-Path $ProjectRoot "runtime\health\latest.json"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $OutputPath -Parent) | Out-Null
    $json = $result | ConvertTo-Json -Depth 8
    $json | Set-Content -Encoding UTF8 $OutputPath
    Write-Output $json

    if ($result.status -ne "ok" -and $env:ALERT_WEBHOOK_URL) {
        try {
            Invoke-RestMethod -Method Post -Uri $env:ALERT_WEBHOOK_URL -ContentType "application/json" -Body $json | Out-Null
        } catch {
            Write-Warning "Alert webhook failed: $($_.Exception.Message)"
        }
    }
    if ($critical) { exit 2 }
}
finally {
    Pop-Location
}
