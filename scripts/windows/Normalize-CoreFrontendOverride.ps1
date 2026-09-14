param(
    [string]$OverridePath = "C:\projects\web\docker-compose.override.yml"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $OverridePath -PathType Leaf)) {
    throw "Compose override was not found: $OverridePath"
}

$content = [System.IO.File]::ReadAllText($OverridePath)
$match = [regex]::Match($content, '(?ms)^  frontend:\r?\n.*?(?=^  hermes-frontend:)')
if (-not $match.Success) {
    throw "The core frontend override block was not found in $OverridePath"
}

$block = $match.Value
$block = [regex]::Replace($block, '(?m)^    image:.*\r?\n', '')
$block = [regex]::Replace($block, '(?m)^    build:.*\r?\n', '')
$block = [regex]::Replace($block, '(?m)^      NEXT_PUBLIC_APP_VERSION:.*\r?\n', '')
$block = [regex]::Replace($block, '(?m)^      NEXT_PUBLIC_GIT_COMMIT:.*\r?\n', '')
$block = [regex]::Replace($block, '(?m)^      NEXT_PUBLIC_BUILD_TIME:.*\r?\n', '')

$updated = $content.Substring(0, $match.Index) + $block + $content.Substring($match.Index + $match.Length)
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OverridePath, $updated, $utf8WithoutBom)

Write-Output "Core frontend release pins removed from $OverridePath"
