param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Commit,
    [string]$ImageTag = "",
    [string]$ProjectRoot = "C:\projects\web",
    [string]$ComposeProjectName = "web",
    [switch]$RestoreUploads,
    [switch]$ConfirmRollback
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRollback) {
    throw "Rollback changes application and database state. Pass -ConfirmRollback."
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

function Read-ImageLabel([string]$ImageRef, [string]$Name) {
    $inspection = @(docker image inspect $ImageRef | ConvertFrom-Json)[0]
    if (-not $inspection.Config.Labels) { return "" }
    $property = $inspection.Config.Labels.PSObject.Properties[$Name]
    if (-not $property) { return "" }
    return "$($property.Value)".Trim()
}

$releaseRoot = Join-Path $ProjectRoot ".release"
$currentPath = Join-Path $releaseRoot "current.json"
$historyPath = Join-Path $releaseRoot "history.ndjson"
$safeRestoreScript = Join-Path $releaseRoot "rollback-safe-Restore-Backup.ps1"
$safeAssertScript = Join-Path $releaseRoot "rollback-safe-Assert-ReleaseState.ps1"
$packageSha = (Get-FileHash $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $ImageTag) {
    $ImageTag = "${Version}-${Commit}-$($packageSha.Substring(0, 12))"
}
$envPath = Join-Path $ProjectRoot ".env"
$prefixLine = Get-Content $envPath | Where-Object { $_ -match '^\s*APP_IMAGE_PREFIX\s*=' } | Select-Object -Last 1
$imagePrefix = if ($prefixLine) { (($prefixLine -split '=', 2)[1]).Trim().Trim('"').Trim("'") } else { "ztqc" }
$backendImage = "${imagePrefix}/backend:${ImageTag}"
$frontendImage = "${imagePrefix}/frontend:${ImageTag}"

docker image inspect $backendImage $frontendImage | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Rollback images are missing. Historical releases must never be rebuilt: $ImageTag"
}
if ((Read-ImageLabel $backendImage "com.ztqc.release.source-sha256") -ne $packageSha -or
    (Read-ImageLabel $frontendImage "com.ztqc.release.source-sha256") -ne $packageSha) {
    throw "Rollback package and immutable images do not share the same source fingerprint"
}
$mcpSourceSha256 = Read-ImageLabel $backendImage "com.ztqc.mcp.source-sha256"
$mcpBinarySha256 = Read-ImageLabel $backendImage "com.ztqc.mcp.binary-sha256"
if (-not $mcpSourceSha256 -or -not $mcpBinarySha256) {
    throw "Rollback backend image is missing MCP provenance labels"
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
Copy-Item -Force (Join-Path $ProjectRoot "scripts\windows\Restore-Backup.ps1") $safeRestoreScript
Copy-Item -Force (Join-Path $ProjectRoot "scripts\windows\Assert-ReleaseState.ps1") $safeAssertScript
$previousReceipt = if (Test-Path $currentPath) { Get-Content $currentPath -Raw | ConvertFrom-Json } else { $null }
$buildTime = (Get-Date).ToUniversalTime().ToString("o")
$env:APP_VERSION = $Version
$env:APP_IMAGE_TAG = $ImageTag
$env:GIT_COMMIT = $Commit
$env:BUILD_TIME = $buildTime
$env:RELEASE_SOURCE_SHA256 = $packageSha
$env:MCP_SOURCE_SHA256 = $mcpSourceSha256
$env:MCP_BINARY_SHA256 = $mcpBinarySha256
$env:COMPOSE_PROJECT_NAME = $ComposeProjectName

Push-Location $ProjectRoot
try {
    docker compose --project-name $ComposeProjectName --env-file $envPath -f docker-compose.yml stop frontend backend ai-worker | Out-Null
    tar -xzf $PackagePath -C $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "Rollback package extraction failed" }

    Set-EnvValue $envPath "APP_VERSION" $Version
    Set-EnvValue $envPath "APP_IMAGE_TAG" $ImageTag
    Set-EnvValue $envPath "GIT_COMMIT" $Commit
    Set-EnvValue $envPath "BUILD_TIME" $buildTime
    Set-EnvValue $envPath "RELEASE_SOURCE_SHA256" $packageSha
    Set-EnvValue $envPath "MCP_SOURCE_SHA256" $mcpSourceSha256
    Set-EnvValue $envPath "MCP_BINARY_SHA256" $mcpBinarySha256

    & $safeRestoreScript `
        -BackupDir $BackupDir `
        -ProjectRoot $ProjectRoot `
        -RestoreUploads:$RestoreUploads `
        -ConfirmRestore
    docker compose --project-name $ComposeProjectName --env-file $envPath -f docker-compose.yml up -d --no-build --no-deps backend ai-worker frontend
    if ($LASTEXITCODE -ne 0) { throw "Rollback service startup failed" }

    $backendId = "$(docker compose --project-name $ComposeProjectName --env-file $envPath -f docker-compose.yml ps -q backend)".Trim()
    $backendImageId = "$(docker inspect --format '{{.Image}}' $backendId)".Trim()
    $receipt = [ordered]@{
        version = $Version
        commit = $Commit
        buildTime = $buildTime
        deployedAt = (Get-Date).ToUniversalTime().ToString("o")
        rollbackOf = if ($previousReceipt) { "$($previousReceipt.version)" } else { "unknown" }
        backupDir = $BackupDir
        package = $PackagePath
        packageSha256 = $packageSha
        core = [ordered]@{
            version = $Version
            commit = $Commit
            buildTime = $buildTime
            sourceSha256 = $packageSha
            imageTag = $ImageTag
            backendImageRef = $backendImage
            backendImageId = $backendImageId
            mcpSourceSha256 = $mcpSourceSha256
            mcpBinarySha256 = $mcpBinarySha256
        }
    }
    $candidateReceipt = Join-Path $releaseRoot "rollback-candidate-$ImageTag.json"
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $candidateReceipt
    & $safeAssertScript -ProjectRoot $ProjectRoot -ComposeProjectName $ComposeProjectName -ReceiptPath $candidateReceipt | Out-Null
    Move-Item -Force $candidateReceipt $currentPath
    ($receipt | ConvertTo-Json -Compress -Depth 6) | Add-Content -Encoding UTF8 $historyPath
    Write-Host "Rollback to immutable image $ImageTag completed and verified"
}
finally {
    Pop-Location
}
