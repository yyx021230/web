param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$TaskName = "ZTQC FRP Tunnel Monitor",
    [int]$ProbeIntervalSeconds = 10,
    [int]$FailureThreshold = 2,
    [int]$ProbeTimeoutSeconds = 4
)

$ErrorActionPreference = "Stop"
if ($ProbeIntervalSeconds -lt 5) { throw "ProbeIntervalSeconds must be at least 5" }
if ($FailureThreshold -lt 1) { throw "FailureThreshold must be at least 1" }
if ($ProbeTimeoutSeconds -lt 1) { throw "ProbeTimeoutSeconds must be at least 1" }

$watchdogScript = Join-Path $ProjectRoot "scripts\windows\Watch-FrpTunnel.ps1"
if (-not (Test-Path $watchdogScript -PathType Leaf)) {
    throw "FRP watchdog script not found: $watchdogScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$watchdogScript`" -Continuous -ProbeIntervalSeconds $ProbeIntervalSeconds -FailureThreshold $FailureThreshold -ProbeTimeoutSeconds $ProbeTimeoutSeconds"
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = "PT30S"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $startupTrigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Output "Installed '$TaskName' as a continuous ${ProbeIntervalSeconds}s monitor"
