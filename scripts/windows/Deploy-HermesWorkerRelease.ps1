param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$Archive,
    [string]$ProjectRoot = 'C:\projects\web'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$releaseRoot = 'D:\ztqc-hermes-release'
$release = Join-Path $releaseRoot $Version
$source = Join-Path $release 'source'
$live = Join-Path $ProjectRoot 'docker-compose.override.yml'
$candidate = Join-Path $release 'compose.candidate.yml'
$receiptPath = Join-Path $release 'release-receipt.json'
$utf8 = New-Object Text.UTF8Encoding($false)
$stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$workerTag = "ztqc/hermes-worker:$Version-$Commit"

function Exec([scriptblock]$Action, [string]$Failure) {
    & $Action
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}

function Container([string]$Name) {
    $value = (docker inspect $Name | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $Name" }
    return @{
        name = $Name
        id = $value.Id
        image = $value.Image
        started = $value.State.StartedAt
        configuredImage = $value.Config.Image
        health = $value.State.Health.Status
    }
}

function WaitHealthy([string]$Name, [string]$Image) {
    for ($i = 0; $i -lt 90; $i++) {
        $value = Container $Name
        if ($value.configuredImage -eq $Image -and $value.health -eq 'healthy') { return $value }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become healthy on $Image"
}

if (-not (Test-Path $Archive -PathType Leaf)) { throw "Missing archive: $Archive" }
if (-not (Test-Path $live -PathType Leaf)) { throw "Missing production override: $live" }
if (Test-Path $receiptPath) { throw "Hermes release is already complete: $receiptPath" }
if (docker image inspect $workerTag 2>$null) { throw "Immutable worker image already exists: $workerTag" }

$active = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_runs WHERE status IN ('queued','claimed','running','generating');"
if ($LASTEXITCODE -ne 0 -or [int]($active.Trim()) -ne 0) { throw 'Hermes has active work; deployment stopped' }
$enabled = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_schedules WHERE enabled=true;"
if ($LASTEXITCODE -ne 0 -or [int]($enabled.Trim()) -ne 0) { throw 'Hermes schedule is enabled; deployment stopped' }

$currentWorker = Container 'web-hermes-worker-1'
$previousImage = $currentWorker.configuredImage
$untouchedNames = @(
    'web-frontend-1', 'web-hermes-frontend-1', 'web-hermes-api-1',
    'web-backend-1', 'web-ai-worker-1', 'web-postgres-1', 'web-redis-1', 'web-minio-1'
)
$untouched = @($untouchedNames | ForEach-Object { Container $_ })
$backup = Join-Path $release ('private\service-before-' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $source, $backup | Out-Null
Copy-Item $live (Join-Path $backup 'docker-compose.override.yml')
if (Test-Path (Join-Path $ProjectRoot '.release\hermes\current.json')) {
    Copy-Item (Join-Path $ProjectRoot '.release\hermes\current.json') (Join-Path $backup 'hermes-current.json')
}
Expand-Archive -Path $Archive -DestinationPath $source -Force

Set-Location $source
Exec {
    docker build --pull=false -f scripts/windows/Dockerfile.hermes-worker-release `
        --build-arg BASE_IMAGE=$previousImage `
        --build-arg APP_VERSION=$Version `
        --build-arg GIT_COMMIT=$Commit `
        --build-arg BUILD_TIME=$stamp `
        -t $workerTag .
} 'Hermes Worker image build failed'

$raw = [IO.File]::ReadAllText($live)
if (-not $raw.Contains($previousImage)) { throw "Live override does not contain current worker image: $previousImage" }
$raw = $raw.Replace($previousImage, $workerTag)
[IO.File]::WriteAllText($candidate, $raw, $utf8)
Exec {
    docker compose --project-name web --project-directory $ProjectRoot `
        -f "$ProjectRoot\docker-compose.yml" -f $candidate --profile hermes config --quiet
} 'Candidate Hermes compose validation failed'

try {
    Exec { docker stop --timeout 2700 web-hermes-worker-1 } 'Hermes Worker drain failed'
    Copy-Item $candidate $live -Force
    Set-Location $ProjectRoot
    Exec { docker compose --profile hermes up -d --no-deps --no-build hermes-worker } 'Hermes Worker cutover failed'
    $worker = WaitHealthy 'web-hermes-worker-1' $workerTag

    $internalCount = docker exec web-hermes-worker-1 python -c "import sys; sys.path.insert(0, '/app/web/ops/xhs_hermes'); from run_daily_8x5 import OnlineData; rows=OnlineData().prompts(); assert rows and all(str(r.get('source_kind') or '') == 'internal' for r in rows); print(len(rows))"
    if ($LASTEXITCODE -ne 0 -or [int]($internalCount.Trim()) -le 0) {
        throw 'Hermes Worker internal prompt catalog verification failed'
    }

    foreach ($old in $untouched) {
        $now = Container $old.name
        if ($now.id -ne $old.id -or $now.image -ne $old.image -or $now.started -ne $old.started) {
            throw "Unexpected service change: $($old.name)"
        }
    }

    $receipt = [ordered]@{
        version = $Version
        status = 'live-verified'
        deployedAt = [DateTime]::UtcNow.ToString('o')
        revision = $Commit
        serviceVersions = @{ worker = $Version }
        image = @{ worker = $worker.image; reference = $workerTag }
        sourceArchiveSha256 = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        scope = 'Hermes production reads the complete paginated internal prompt catalog only'
        internalPromptCount = [int]($internalCount.Trim())
        scheduleEnabled = $false
        generationRequests = 0
        databaseMigration = $false
        acceptance = @{ workerHealthy = $true; internalCatalogVerified = $true; untouchedServices = $true }
        rollback = @{
            composeBackup = (Join-Path $backup 'docker-compose.override.yml')
            previousWorker = $previousImage
            databaseRestore = $false
        }
    }
    $json = $receipt | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($receiptPath, $json, $utf8)
    $hermesReceipt = Join-Path $ProjectRoot '.release\hermes\current.json'
    [IO.File]::WriteAllText($hermesReceipt, $json, $utf8)

    $corePath = Join-Path $ProjectRoot '.release\current.json'
    $core = Get-Content $corePath -Raw | ConvertFrom-Json
    $pointer = @{ version = $Version; receipt = $hermesReceipt }
    if ($core.PSObject.Properties.Name -contains 'hermesRelease') {
        $core.hermesRelease = $pointer
    } else {
        $core | Add-Member -NotePropertyName hermesRelease -NotePropertyValue $pointer
    }
    [IO.File]::WriteAllText($corePath, ($core | ConvertTo-Json -Depth 20), $utf8)
    Write-Output ($receipt | ConvertTo-Json -Depth 20 -Compress)
} catch {
    Copy-Item (Join-Path $backup 'docker-compose.override.yml') $live -Force
    Set-Location $ProjectRoot
    docker compose --profile hermes up -d --no-deps --no-build hermes-worker | Out-Host
    throw
}
