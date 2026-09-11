param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$TaskName = "ZTQC Production Recovery",
    [string]$RunAsUser = "$env:COMPUTERNAME\$env:USERNAME",
    [Parameter(Mandatory = $true)][string]$RunAsPassword,
    [int]$IntervalMinutes = 5
)

$ErrorActionPreference = "Stop"
if ($IntervalMinutes -lt 1) { throw "IntervalMinutes must be at least 1" }

$recoveryScript = Join-Path $ProjectRoot "scripts\windows\Ensure-ProductionRunning.ps1"
if (-not (Test-Path $recoveryScript -PathType Leaf)) {
    throw "Recovery script not found: $recoveryScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$recoveryScript`" -ProjectRoot `"$ProjectRoot`""
$dockerAction = New-ScheduledTaskAction `
    -Execute "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$dockerTrigger = New-ScheduledTaskTrigger -AtStartup
$dockerTrigger.Delay = "PT30S"
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = "PT1M"
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$dockerSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId $RunAsUser `
    -LogonType Password `
    -RunLevel Highest
$dockerTask = New-ScheduledTask `
    -Action $dockerAction `
    -Trigger $dockerTrigger `
    -Settings $dockerSettings `
    -Principal $principal
Register-ScheduledTask `
    -TaskName "ZTQC Docker Desktop" `
    -InputObject $dockerTask `
    -User $RunAsUser `
    -Password $RunAsPassword `
    -Force | Out-Null

$recoveryPrincipal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$recoveryTask = New-ScheduledTask `
    -Action $action `
    -Trigger @($startupTrigger, $repeatTrigger) `
    -Settings $settings `
    -Principal $recoveryPrincipal

Register-ScheduledTask `
    -TaskName $TaskName `
    -InputObject $recoveryTask `
    -Force | Out-Null

Write-Host "Installed 'ZTQC Docker Desktop' at startup as $RunAsUser"
Write-Host "Installed '$TaskName' for startup and every $IntervalMinutes minutes as SYSTEM"
