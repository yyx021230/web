param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$ComposeProjectName = "web",
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$receiptPath = Join-Path $ProjectRoot ".release\current.json"
$envPath = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $receiptPath -PathType Leaf)) { throw "Missing release receipt: $receiptPath" }
if (-not (Test-Path $envPath -PathType Leaf)) { throw "Missing production environment: $envPath" }

$receipt = Get-Content $receiptPath -Raw | ConvertFrom-Json
if (-not $receipt.core -or -not $receipt.core.imageTag) {
    throw "Release receipt is not pinned; run a canonical release before using this recovery command"
}

function Set-EnvValue([string]$Path, [string]$Name, [string]$Value) {
    $lines = @((Get-Content $Path -ErrorAction Stop))
    $pattern = "^\s*$([regex]::Escape($Name))\s*="
    $replacement = "${Name}=${Value}"
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match $pattern) {
            if (-not $found) { $replacement }
            $found = $true
        } else {
            $line
        }
    }
    if (-not $found) { $updated += $replacement }
    $updated | Set-Content -Encoding UTF8 $Path
}

$env:APP_IMAGE_TAG = "$($receipt.core.imageTag)"
$env:APP_VERSION = "$($receipt.core.version)"
$env:GIT_COMMIT = "$($receipt.core.commit)"
$env:BUILD_TIME = "$($receipt.core.buildTime)"
$env:RELEASE_SOURCE_SHA256 = "$($receipt.core.sourceSha256)"
$env:MCP_SOURCE_SHA256 = "$($receipt.core.mcpSourceSha256)"
$env:MCP_BINARY_SHA256 = "$($receipt.core.mcpBinarySha256)"
$env:COMPOSE_PROJECT_NAME = $ComposeProjectName

Set-EnvValue $envPath "APP_IMAGE_TAG" $env:APP_IMAGE_TAG
Set-EnvValue $envPath "APP_VERSION" $env:APP_VERSION
Set-EnvValue $envPath "GIT_COMMIT" $env:GIT_COMMIT
Set-EnvValue $envPath "BUILD_TIME" $env:BUILD_TIME
Set-EnvValue $envPath "RELEASE_SOURCE_SHA256" $env:RELEASE_SOURCE_SHA256
Set-EnvValue $envPath "MCP_SOURCE_SHA256" $env:MCP_SOURCE_SHA256
Set-EnvValue $envPath "MCP_BINARY_SHA256" $env:MCP_BINARY_SHA256

Push-Location $ProjectRoot
try {
    if ($Restart) {
        docker compose --project-name $ComposeProjectName --env-file $envPath -f docker-compose.yml stop backend ai-worker | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to stop production core services" }
    }
    docker compose --project-name $ComposeProjectName --env-file $envPath -f docker-compose.yml up -d --no-build --no-deps backend ai-worker | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to start pinned production core services" }
    & (Join-Path $ProjectRoot "scripts\windows\Assert-ReleaseState.ps1") -ProjectRoot $ProjectRoot -ComposeProjectName $ComposeProjectName
}
finally {
    Pop-Location
}
