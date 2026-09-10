param(
    [string]$ProjectRoot = "C:\projects\web",
    [string]$ComposeProjectName = "web",
    [string]$ReceiptPath = ""
)

$ErrorActionPreference = "Stop"
$currentPath = if ($ReceiptPath) { $ReceiptPath } else { Join-Path $ProjectRoot ".release\current.json" }
if (-not (Test-Path $currentPath -PathType Leaf)) {
    throw "Missing release receipt: $currentPath"
}

function Get-ServiceContainer([string]$Service) {
    $ids = @(docker ps --filter "label=com.docker.compose.project=$ComposeProjectName" --filter "label=com.docker.compose.service=$Service" --format "{{.ID}}")
    if ($LASTEXITCODE -ne 0 -or $ids.Count -ne 1) {
        throw "Expected one running $Service container, found $($ids.Count)"
    }
    return "$($ids[0])".Trim()
}

function Read-EnvValue($Entries, [string]$Name) {
    $prefix = "${Name}="
    $entry = @($Entries | Where-Object { $_.StartsWith($prefix) } | Select-Object -Last 1)
    if ($entry.Count -eq 0) { return "" }
    return "$($entry[0].Substring($prefix.Length))".Trim()
}

$receipt = Get-Content $currentPath -Raw | ConvertFrom-Json
if (-not $receipt.core) {
    throw "Release receipt is legacy and has no verified core component block"
}

$backendId = Get-ServiceContainer "backend"
$workerId = Get-ServiceContainer "ai-worker"
$backend = @(docker inspect $backendId | ConvertFrom-Json)[0]
$worker = @(docker inspect $workerId | ConvertFrom-Json)[0]
$image = @(docker image inspect $backend.Image | ConvertFrom-Json)[0]

$actual = [ordered]@{
    version = Read-EnvValue $backend.Config.Env "APP_VERSION"
    commit = Read-EnvValue $backend.Config.Env "GIT_COMMIT"
    buildTime = Read-EnvValue $backend.Config.Env "BUILD_TIME"
    sourceSha256 = Read-EnvValue $backend.Config.Env "RELEASE_SOURCE_SHA256"
    imageRef = "$($backend.Config.Image)"
    imageId = "$($backend.Image)"
    imageVersion = Read-EnvValue $image.Config.Env "APP_VERSION"
    imageCommit = Read-EnvValue $image.Config.Env "GIT_COMMIT"
    imageSourceSha256 = Read-EnvValue $image.Config.Env "RELEASE_SOURCE_SHA256"
    mcpSourceSha256 = Read-EnvValue $backend.Config.Env "MCP_SOURCE_SHA256"
    mcpBinarySha256 = Read-EnvValue $backend.Config.Env "MCP_BINARY_SHA256"
    imageMcpSourceSha256 = Read-EnvValue $image.Config.Env "MCP_SOURCE_SHA256"
    imageMcpBinarySha256 = Read-EnvValue $image.Config.Env "MCP_BINARY_SHA256"
    workerVersion = Read-EnvValue $worker.Config.Env "APP_VERSION"
    workerCommit = Read-EnvValue $worker.Config.Env "GIT_COMMIT"
    workerSourceSha256 = Read-EnvValue $worker.Config.Env "RELEASE_SOURCE_SHA256"
}

$expected = $receipt.core
$checks = [ordered]@{
    backendWorkerImage = "$($backend.Image)" -eq "$($worker.Image)"
    version = $actual.version -eq "$($expected.version)"
    commit = $actual.commit -eq "$($expected.commit)"
    sourceSha256 = $actual.sourceSha256 -eq "$($expected.sourceSha256)"
    imageRef = $actual.imageRef -eq "$($expected.backendImageRef)"
    imageId = $actual.imageId -eq "$($expected.backendImageId)"
    bakedVersion = $actual.imageVersion -eq "$($expected.version)"
    bakedCommit = $actual.imageCommit -eq "$($expected.commit)"
    bakedSourceSha256 = $actual.imageSourceSha256 -eq "$($expected.sourceSha256)"
    mcpSourceSha256 = $actual.mcpSourceSha256 -eq "$($expected.mcpSourceSha256)"
    mcpBinarySha256 = $actual.mcpBinarySha256 -eq "$($expected.mcpBinarySha256)"
    bakedMcpSourceSha256 = $actual.imageMcpSourceSha256 -eq "$($expected.mcpSourceSha256)"
    bakedMcpBinarySha256 = $actual.imageMcpBinarySha256 -eq "$($expected.mcpBinarySha256)"
    workerVersion = $actual.workerVersion -eq "$($expected.version)"
    workerCommit = $actual.workerCommit -eq "$($expected.commit)"
    workerSourceSha256 = $actual.workerSourceSha256 -eq "$($expected.sourceSha256)"
}

$failed = @($checks.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
$result = [ordered]@{
    verified = $failed.Count -eq 0
    checkedAt = (Get-Date).ToUniversalTime().ToString("o")
    expected = $expected
    actual = $actual
    checks = $checks
}
$result | ConvertTo-Json -Depth 8
if ($failed.Count -gt 0) {
    throw "Production release drift detected: $($failed -join ', ')"
}
