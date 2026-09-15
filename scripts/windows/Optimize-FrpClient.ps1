param(
    [string]$ConfigPath = "C:\ProgramData\frp\frpc.toml",
    [string]$FrpExePath = "C:\ProgramData\frp\frpc.exe",
    [string]$TaskName = "FRP-Windows-Web-Tunnel"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $ConfigPath -PathType Leaf)) { throw "FRP config not found: $ConfigPath" }
if (-not (Test-Path $FrpExePath -PathType Leaf)) { throw "FRP executable not found: $FrpExePath" }

$original = [IO.File]::ReadAllText($ConfigPath)
if ([regex]::Matches($original, '(?m)^\s*\[\[proxies\]\]\s*$').Count -ne 1 -or
    $original -notmatch '(?m)^\s*name\s*=\s*"windows-web"\s*$') {
    throw "Unexpected FRP configuration; expected exactly one windows-web proxy"
}

$parts = [regex]::Split($original, '(?m)(?=^\s*\[\[proxies\]\]\s*$)', 2)
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
$root = Set-TomlValue $root "transport.poolCount" "20"
$root = Set-TomlValue $root "transport.tcpMux" "true"
$root = Set-TomlValue $root "transport.tcpMuxKeepaliveInterval" "15"
$root = Set-TomlValue $root "transport.heartbeatInterval" "-1"
$root = Set-TomlValue $root "transport.dialServerKeepalive" "30"

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
try {
    [IO.File]::WriteAllText($ConfigPath, $candidate, $utf8WithoutBom)
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700
    Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -eq $FrpExePath -and $_.CommandLine.Contains($ConfigPath) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-ScheduledTask -TaskName $TaskName
} catch {
    Copy-Item $backupPath $ConfigPath -Force
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    throw
} finally {
    Remove-Item $candidatePath -Force -ErrorAction SilentlyContinue
}

Write-Output "FRP transport settings updated; backup: $backupPath"
