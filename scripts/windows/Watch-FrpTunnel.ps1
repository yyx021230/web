param(
    [string]$LocalUrl = "http://127.0.0.1:3000/prompts",
    [string]$PublicUrl = "http://47.98.127.132:18080/prompts",
    [string]$FrpTaskName = "FRP-Windows-Web-Tunnel",
    [string]$FrpConfigPath = "C:\ProgramData\frp\frpc.toml",
    [string]$StateRoot = "C:\ProgramData\frp\watchdog",
    [int]$FailureThreshold = 2,
    [int]$ProbeTimeoutSeconds = 6
)

$ErrorActionPreference = "Stop"
$statePath = Join-Path $StateRoot "state.json"
$logPath = Join-Path $StateRoot "watchdog.log"
$mutex = New-Object System.Threading.Mutex($false, "Global\ZTQCFrpTunnelWatchdog")
$mutexHeld = $false

function Write-WatchdogLog([string]$Message) {
    Add-Content -Encoding UTF8 -Path $logPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}

function Test-HttpEndpoint([string]$Uri) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Method Head -TimeoutSec $ProbeTimeoutSeconds -Uri $Uri
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Read-WatchdogState {
    if (-not (Test-Path $statePath -PathType Leaf)) {
        return [pscustomobject]@{ consecutivePublicFailures = 0 }
    }
    try {
        return Get-Content $statePath -Raw | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{ consecutivePublicFailures = 0 }
    }
}

function Write-WatchdogState([int]$Failures, [string]$Status, [bool]$Recovered) {
    [ordered]@{
        checkedAt = (Get-Date).ToUniversalTime().ToString("o")
        status = $Status
        consecutivePublicFailures = $Failures
        recovered = $Recovered
    } | ConvertTo-Json | Set-Content -Encoding UTF8 $statePath
}

function Restart-FrpEntry {
    $matchingProcesses = @(
        Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ExecutablePath -eq "C:\ProgramData\frp\frpc.exe" -and
                $_.CommandLine -and $_.CommandLine.Contains($FrpConfigPath)
            }
    )
    if ($matchingProcesses.Count -gt 1) {
        throw "Refusing to restart an ambiguous FRP process set"
    }

    # Kill the exact child first. Stopping a running Task Scheduler action can
    # otherwise block for roughly 30 seconds while frpc is already unusable.
    foreach ($process in $matchingProcesses) {
        $remaining = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ProcessId)" -ErrorAction SilentlyContinue
        if ($remaining -and $remaining.ExecutablePath -eq $process.ExecutablePath -and
            $remaining.CommandLine -eq $process.CommandLine) {
            Stop-Process -Id $process.ProcessId -Force
        }
    }
    foreach ($attempt in 1..10) {
        if ((Get-ScheduledTask -TaskName $FrpTaskName).State -ne "Running") { break }
        Start-Sleep -Milliseconds 200
    }
    Stop-ScheduledTask -TaskName $FrpTaskName -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $FrpTaskName
}

New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
try {
    $mutexHeld = $mutex.WaitOne(0)
    if (-not $mutexHeld) { exit 0 }

    $localOk = Test-HttpEndpoint $LocalUrl
    if (-not $localOk) {
        Write-WatchdogState 0 "local_service_unavailable" $false
        Write-WatchdogLog "Skipped FRP recovery because the local web service is unavailable"
        exit 0
    }

    if (Test-HttpEndpoint $PublicUrl) {
        Write-WatchdogState 0 "healthy" $false
        exit 0
    }

    $state = Read-WatchdogState
    $failures = [int]$state.consecutivePublicFailures + 1
    if ($failures -lt $FailureThreshold) {
        Write-WatchdogState $failures "public_probe_failed" $false
        exit 0
    }

    Write-WatchdogLog "Public probe failed $failures consecutive times while local service is healthy; restarting FRP entry only"
    Restart-FrpEntry

    foreach ($attempt in 1..8) {
        Start-Sleep -Seconds 2
        if (Test-HttpEndpoint $PublicUrl) {
            Write-WatchdogState 0 "recovered" $true
            Write-WatchdogLog "FRP public entry recovered after restart"
            exit 0
        }
    }

    Write-WatchdogState $failures "recovery_failed" $false
    Write-WatchdogLog "FRP restart completed but the public entry is still unavailable"
    exit 1
} catch {
    Write-WatchdogLog "Watchdog failed: $($_.Exception.Message)"
    Write-WatchdogState 0 "watchdog_failed" $false
    throw
} finally {
    if ($mutexHeld) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
