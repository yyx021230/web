param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$BackupRoot = "D:\ztqc-backups\web",
    [string]$TaskName = "ZTQC Web Daily Backup",
    [string]$RunAt = "02:30",
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$runTime = [datetime]::ParseExact($RunAt, "HH:mm", $null)
$backupScript = Join-Path $ProjectRoot "scripts\windows\Backup-Release.ps1"
if (-not (Test-Path $backupScript)) {
    throw "Backup script not found: $backupScript"
}

$runtimeDir = Join-Path $ProjectRoot "runtime\backup"
$stdoutPath = Join-Path $runtimeDir "backup.stdout.log"
$stderrPath = Join-Path $runtimeDir "backup.stderr.log"
New-Item -ItemType Directory -Force -Path $runtimeDir, $BackupRoot | Out-Null

$escapedScript = $backupScript.Replace("'", "''")
$escapedProject = $ProjectRoot.Replace("'", "''")
$escapedBackupRoot = $BackupRoot.Replace("'", "''")
$escapedStdout = $stdoutPath.Replace("'", "''")
$escapedStderr = $stderrPath.Replace("'", "''")
$command = "& '$escapedScript' -ProjectRoot '$escapedProject' -BackupRoot '$escapedBackupRoot' -RetentionDays $RetentionDays 1>> '$escapedStdout' 2>> '$escapedStderr'"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$command`""
$trigger = New-ScheduledTaskTrigger -Daily -At $runTime
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Installed '$TaskName' at $RunAt every day"
Write-Host "Backup root: $BackupRoot"
