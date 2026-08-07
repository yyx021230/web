param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$TaskName = "ZTQC Web Health Monitor",
    [int]$IntervalMinutes = 5
)

$ErrorActionPreference = "Stop"
if ($IntervalMinutes -lt 1) {
    throw "IntervalMinutes must be at least 1"
}

$healthScript = Join-Path $ProjectRoot "scripts\windows\Test-SystemHealth.ps1"
if (-not (Test-Path $healthScript)) {
    throw "Health script not found: $healthScript"
}

$runtimeDir = Join-Path $ProjectRoot "runtime\health"
$stdoutPath = Join-Path $runtimeDir "monitor.stdout.log"
$stderrPath = Join-Path $runtimeDir "monitor.stderr.log"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$escapedScript = $healthScript.Replace("'", "''")
$escapedProject = $ProjectRoot.Replace("'", "''")
$escapedStdout = $stdoutPath.Replace("'", "''")
$escapedStderr = $stderrPath.Replace("'", "''")
$command = "& '$escapedScript' -ProjectRoot '$escapedProject' 1>> '$escapedStdout' 2>> '$escapedStderr'"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$command`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Installed '$TaskName' with a ${IntervalMinutes}-minute interval"
Write-Host "Latest status: $(Join-Path $runtimeDir 'latest.json')"
