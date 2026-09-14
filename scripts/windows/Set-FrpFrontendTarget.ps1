param(
    [int]$TargetPort = 3000,
    [string]$ConfigPath = "C:\ProgramData\frp\frpc.toml"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ConfigPath -PathType Leaf)) {
    throw "FRP client configuration was not found: $ConfigPath"
}

$content = [System.IO.File]::ReadAllText($ConfigPath)
$updated = [regex]::Replace(
    $content,
    '(?m)^localPort\s*=\s*\d+\s*$',
    "localPort = $TargetPort"
)
if ($updated -eq $content -and $content -notmatch "(?m)^localPort\s*=\s*$TargetPort\s*$") {
    throw "No localPort setting was found in $ConfigPath"
}

# frpc rejects a TOML file with a UTF-8 BOM on this Windows host.
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ConfigPath, $updated, $utf8WithoutBom)

Write-Output "FRP frontend target updated to 127.0.0.1:$TargetPort"
