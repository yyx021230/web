param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$ComposeProjectName = "web",
    [string]$DockerTaskName = "ZTQC Docker Desktop",
    [int]$DockerReadyTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"
$runtimeDir = Join-Path $ProjectRoot "runtime\recovery"
$logPath = Join-Path $runtimeDir "production-recovery.log"
$statusPath = Join-Path $runtimeDir "latest.json"
$releaseRoot = Join-Path $ProjectRoot ".release"
$deploymentLockPath = Join-Path $releaseRoot "deploy.lock"
$mutex = New-Object System.Threading.Mutex($false, "Global\ZTQCProductionRecovery")
$mutexHeld = $false

function Write-RecoveryLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -Encoding UTF8 -Path $logPath -Value $line
}

function Test-DockerEngine {
    cmd.exe /d /c "docker info 1>nul 2>nul"
    return $LASTEXITCODE -eq 0
}

function Test-HttpOk([string]$Uri) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri $Uri
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-DeploymentInProgress {
    New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
    try {
        $probe = [System.IO.File]::Open(
            $deploymentLockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $probe.Dispose()
        return $false
    } catch [System.IO.IOException] {
        return $true
    }
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$result = [ordered]@{
    checkedAt = (Get-Date).ToUniversalTime().ToString("o")
    status = "unknown"
    dockerRecovered = $false
    applicationRecovered = $false
    message = ""
}

try {
    $mutexHeld = $mutex.WaitOne(0)
    if (-not $mutexHeld) {
        $result.status = "skipped"
        $result.message = "Another recovery check is still running"
        exit 0
    }

    if (Test-DeploymentInProgress) {
        $result.status = "skipped"
        $result.message = "A production deployment is active"
        Write-RecoveryLog "Skipped because a production deployment owns the release lock"
        exit 0
    }

    if (-not (Test-DockerEngine)) {
        Write-RecoveryLog "Docker engine is unavailable; starting Docker Desktop"
        try { Start-Service com.docker.service -ErrorAction Stop } catch {
            Write-RecoveryLog "Docker service start warning: $($_.Exception.Message)"
        }

        $dockerTask = Get-ScheduledTask -TaskName $DockerTaskName -ErrorAction SilentlyContinue
        if (-not $dockerTask) {
            throw "Docker Desktop startup task is not installed: $DockerTaskName"
        }
        Start-ScheduledTask -TaskName $DockerTaskName

        $deadline = (Get-Date).AddSeconds($DockerReadyTimeoutSeconds)
        do {
            Start-Sleep -Seconds 2
            if (Test-DockerEngine) { break }
        } while ((Get-Date) -lt $deadline)

        if (-not (Test-DockerEngine)) {
            throw "Docker engine did not become ready within $DockerReadyTimeoutSeconds seconds"
        }
        $result.dockerRecovered = $true
        Write-RecoveryLog "Docker engine recovered"
    }

    $backendReady = Test-HttpOk "http://127.0.0.1:8000/health/ready"
    $frontendReady = Test-HttpOk "http://127.0.0.1:3000/"
    if (-not $backendReady -or -not $frontendReady) {
        Write-RecoveryLog "Application endpoint unavailable; restoring the pinned production release"
        $startScript = Join-Path $ProjectRoot "scripts\windows\Start-Production.ps1"
        if (-not (Test-Path $startScript -PathType Leaf)) {
            throw "Production recovery script not found: $startScript"
        }

        $lastError = $null
        foreach ($attempt in 1..3) {
            try {
                & $startScript -ProjectRoot $ProjectRoot -ComposeProjectName $ComposeProjectName
                $lastError = $null
                break
            } catch {
                $lastError = $_
                Write-RecoveryLog "Application recovery attempt $attempt failed: $($_.Exception.Message)"
                if ($attempt -lt 3) { Start-Sleep -Seconds 20 }
            }
        }
        if ($lastError) { throw $lastError }
        $result.applicationRecovered = $true
    }

    if (-not (Test-HttpOk "http://127.0.0.1:8000/health/ready")) {
        throw "Backend readiness endpoint is unavailable after recovery"
    }
    if (-not (Test-HttpOk "http://127.0.0.1:3000/")) {
        throw "Frontend is unavailable after recovery"
    }

    $result.status = "ok"
    $result.message = if ($result.dockerRecovered -or $result.applicationRecovered) {
        "Production service recovered"
    } else {
        "Production service is healthy"
    }
    if ($result.dockerRecovered -or $result.applicationRecovered) {
        Write-RecoveryLog $result.message
    }
} catch {
    $result.status = "failed"
    $result.message = $_.Exception.Message
    Write-RecoveryLog "Recovery failed: $($_.Exception.Message)"
    throw
} finally {
    $result.checkedAt = (Get-Date).ToUniversalTime().ToString("o")
    $result | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $statusPath
    if ($mutexHeld) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
