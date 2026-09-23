param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$ComposeProjectName = "web",
    [string]$RunnerName = "",
    [int]$TargetEnvironmentId = 0,
    [string]$TargetAccountName = "",
    [switch]$IdentityOnly,
    [switch]$ExportOnly,
    [switch]$KeepBrowserOpen
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

if (-not $RunnerName) {
    # Build the default name from code points so this file remains ASCII-safe
    # when it is opened by Windows PowerShell 5.
    $RunnerName = -join ([char]0x6D4B, [char]0x8BD5, [char]0x32)
}
if ($TargetEnvironmentId -gt 0 -and $TargetAccountName) {
    throw "Use only one of TargetEnvironmentId and TargetAccountName"
}
if ($IdentityOnly -and $ExportOnly) {
    throw "Use only one of IdentityOnly and ExportOnly"
}

$pythonScript = Join-Path $PSScriptRoot "sync_xhs_creator_center.py"
$composeFile = Join-Path $ProjectRoot "docker-compose.yml"
$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $pythonScript -PathType Leaf)) {
    throw "Missing Python script: $pythonScript"
}
if (-not (Test-Path $composeFile -PathType Leaf)) {
    throw "Missing compose file: $composeFile"
}
if (-not (Test-Path $envFile -PathType Leaf)) {
    throw "Missing environment file: $envFile"
}

$pythonArgs = @("-", "--runner-name", $RunnerName)
if ($TargetEnvironmentId -gt 0) {
    $pythonArgs += @("--target-environment-id", "$TargetEnvironmentId")
}
if ($TargetAccountName) {
    $pythonArgs += @("--target-account-name", $TargetAccountName)
}
if ($IdentityOnly) {
    $pythonArgs += "--identity-only"
}
if ($ExportOnly) {
    $pythonArgs += "--export-only"
}
if ($KeepBrowserOpen) {
    $pythonArgs += "--keep-browser-open"
}

$logRoot = Join-Path $ProjectRoot "runtime\creator-center-sync"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$logPath = Join-Path $logRoot ("sync-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$dockerArgs = @(
    "compose",
    "--project-name", $ComposeProjectName,
    "--env-file", $envFile,
    "-f", $composeFile,
    "exec", "-T", "backend", "python"
) + $pythonArgs

Push-Location $ProjectRoot
try {
    $backendContainer = (& docker compose --project-name $ComposeProjectName --env-file $envFile -f $composeFile ps -q backend | Select-Object -Last 1).Trim()
    if (-not $backendContainer) {
        throw "The backend container is not running"
    }

    Write-Host "Running one-shot creator-center sync through runner: $RunnerName"
    Write-Host "Log: $logPath"
    Write-Host "The creator-center export may take several minutes."
    $stdoutPath = "$logPath.stdout"
    $stderrPath = "$logPath.stderr"
    $quotedDockerArgs = @(
        $dockerArgs | ForEach-Object {
            '"' + ($_.Replace('"', '\"')) + '"'
        }
    ) -join " "
    $syncProcess = Start-Process `
        -FilePath "docker.exe" `
        -ArgumentList $quotedDockerArgs `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardInput $pythonScript `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath
    $syncExitCode = $syncProcess.ExitCode

    $stdoutText = if (Test-Path $stdoutPath) { Get-Content -Raw -Encoding UTF8 $stdoutPath } else { "" }
    $stderrText = if (Test-Path $stderrPath) { Get-Content -Raw -Encoding UTF8 $stderrPath } else { "" }
    $combinedText = @($stdoutText, $stderrText) | Where-Object { $_ }
    [System.IO.File]::WriteAllText(
        $logPath,
        ($combinedText -join [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
    Remove-Item $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    if ($stdoutText) { Write-Host $stdoutText }
    if ($stderrText) { Write-Host $stderrText }
    if ($syncExitCode -ne 0) {
        throw "Creator-center sync failed with exit code $syncExitCode. See $logPath"
    }
}
finally {
    Pop-Location
}
