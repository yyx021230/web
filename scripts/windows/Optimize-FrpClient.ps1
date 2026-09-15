param(
    [string]$ConfigPath = "C:\ProgramData\frp\frpc.toml",
    [string]$FrpExePath = "C:\ProgramData\frp\frpc.exe",
    [string]$TaskName = "FRP-Windows-Web-Tunnel",
    [string]$MonitorTaskName = "ZTQC FRP Tunnel Monitor",
    [string]$PublicUrl = "http://47.98.127.132:18080/prompts",
    [int]$PoolCount = 5
)

$ErrorActionPreference = "Stop"
if ($PoolCount -lt 1 -or $PoolCount -gt 20) { throw "PoolCount must be between 1 and 20" }
if (-not (Test-Path $ConfigPath -PathType Leaf)) { throw "FRP config not found: $ConfigPath" }
if (-not (Test-Path $FrpExePath -PathType Leaf)) { throw "FRP executable not found: $FrpExePath" }

$original = [IO.File]::ReadAllText($ConfigPath)
if ([regex]::Matches($original, '(?m)^\s*\[\[proxies\]\]\s*$').Count -ne 1 -or
    $original -notmatch '(?m)^\s*name\s*=\s*"windows-web"\s*$') {
    throw "Unexpected FRP configuration; expected exactly one windows-web proxy"
}

$proxyBoundary = [regex]::new('(?m)(?=^\s*\[\[proxies\]\]\s*$)')
$parts = $proxyBoundary.Split($original, 2)
if ($parts.Count -ne 2 -or $parts[1] -notmatch '(?m)^\s*\[\[proxies\]\]\s*$') {
    throw "Unable to preserve the windows-web proxy section"
}
$root = $parts[0].TrimEnd()
$proxy = $parts[1].Trim()

function Set-TomlValue([string]$Content, [string]$Name, [string]$Value) {
    $pattern = "(?m)^\s*$([regex]::Escape($Name))\s*=.*$"
    if ($Content -match $pattern) {
        return [regex]::Replace($Content, $pattern, "$Name = $Value", 1)
    }
    return "$Content`r`n$Name = $Value"
}

$root = Set-TomlValue $root "loginFailExit" "false"
$root = Set-TomlValue $root "transport.poolCount" "$PoolCount"
$root = Set-TomlValue $root "transport.tcpMux" "true"
$root = Set-TomlValue $root "transport.tcpMuxKeepaliveInterval" "10"
$root = Set-TomlValue $root "transport.heartbeatInterval" "-1"
$root = Set-TomlValue $root "transport.dialServerKeepalive" "15"

$candidate = "$root`r`n`r`n$proxy`r`n"
$candidatePath = "$ConfigPath.candidate"
$backupPath = "$ConfigPath.$(Get-Date -Format 'yyyyMMdd_HHmmss').bak"
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($candidatePath, $candidate, $utf8WithoutBom)

& $FrpExePath verify -c $candidatePath
if ($LASTEXITCODE -ne 0) {
    Remove-Item $candidatePath -Force -ErrorAction SilentlyContinue
    throw "FRP candidate configuration failed validation"
}

Copy-Item $ConfigPath $backupPath -ErrorAction Stop
$monitorTask = Get-ScheduledTask -TaskName $MonitorTaskName -ErrorAction SilentlyContinue
if ($monitorTask) {
    Stop-ScheduledTask -TaskName $MonitorTaskName -ErrorAction SilentlyContinue
}
try {
    [IO.File]::WriteAllText($ConfigPath, $candidate, $utf8WithoutBom)
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700
    Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -eq $FrpExePath -and $_.CommandLine.Contains($ConfigPath) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-ScheduledTask -TaskName $TaskName

    $publicReady = $false
    foreach ($attempt in 1..10) {
        Start-Sleep -Seconds 2
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Head -TimeoutSec 4 -Uri $PublicUrl
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                $publicReady = $true
                break
            }
        } catch {}
    }
    if (-not $publicReady) { throw "FRP public entry did not recover with the candidate configuration" }
} catch {
    Copy-Item $backupPath $ConfigPath -Force
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -eq $FrpExePath -and $_.CommandLine.Contains($ConfigPath) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    throw
} finally {
    Remove-Item $candidatePath -Force -ErrorAction SilentlyContinue
    if ($monitorTask) {
        Start-ScheduledTask -TaskName $MonitorTaskName -ErrorAction SilentlyContinue
    }
}

Write-Output "FRP transport settings updated with poolCount=$PoolCount; backup: $backupPath"
