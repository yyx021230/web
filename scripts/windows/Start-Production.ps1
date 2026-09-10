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

    # Frontend is released independently by the Hermes bundle. Recover the
    # existing Compose container in place so this command never replaces that
    # image with the core release tag.
    $frontendIds = @(
        docker ps -aq `
            --filter "label=com.docker.compose.project=$ComposeProjectName" `
            --filter "label=com.docker.compose.service=frontend" |
            Where-Object { $_ -and $_.Trim() }
    )
    if ($frontendIds.Count -ne 1) {
        throw "Expected one existing production frontend container, found $($frontendIds.Count)"
    }
    $frontendRunning = docker inspect -f "{{.State.Running}}" $frontendIds[0]
    if ($LASTEXITCODE -ne 0) { throw "Failed to inspect production frontend" }
    if ($frontendRunning.Trim().ToLowerInvariant() -ne "true") {
        docker start $frontendIds[0] | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to start existing production frontend" }
    }

    & (Join-Path $ProjectRoot "scripts\windows\Assert-ReleaseState.ps1") -ProjectRoot $ProjectRoot -ComposeProjectName $ComposeProjectName
    $frontendResponse = Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Uri "http://127.0.0.1:3000/"
    if ($frontendResponse.StatusCode -ne 200) { throw "Production frontend did not return HTTP 200" }
}
finally {
    Pop-Location
}
