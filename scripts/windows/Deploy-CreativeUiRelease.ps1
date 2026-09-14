param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$Archive,
    [string]$ProjectRoot = 'C:\projects\web'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$releaseRoot = 'D:\ztqc-hermes-release'
$release = Join-Path $releaseRoot "$Version-ui"
$source = Join-Path $release 'source'
$live = Join-Path $ProjectRoot 'docker-compose.override.yml'
$candidate = Join-Path $release 'compose.candidate.yml'
$receiptPath = Join-Path $release 'release-receipt.json'
$utf8 = New-Object Text.UTF8Encoding($false)
$stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$frontendTag = "ztqc/frontend:$Version-$Commit-hermes"
$apiTag = "ztqc/hermes-api:$Version-$Commit"

function Exec([scriptblock]$Action, [string]$Failure) {
    & $Action
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}

function Container([string]$Name) {
    $value = (docker inspect $Name | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $Name" }
    $health = if ($value.State.Health) { $value.State.Health.Status } else { 'none' }
    return @{
        name = $Name
        id = $value.Id
        image = $value.Image
        started = $value.State.StartedAt
        configuredImage = $value.Config.Image
        health = $health
    }
}

function SetServiceEnvironment(
    [string]$Text,
    [string]$Service,
    [string]$Key,
    [string]$Value
) {
    $servicePattern = [regex]::new(
        '(?ms)^  ' + [regex]::Escape($Service) + ':\r?\n.*?(?=^  [A-Za-z0-9_-]+:\r?\n|\z)'
    )
    $serviceMatches = $servicePattern.Matches($Text)
    if ($serviceMatches.Count -ne 1) { throw "Cannot uniquely locate service block: $Service" }

    $match = $serviceMatches[0]
    $block = $match.Value
    $keyPattern = [regex]::new('(?m)^      ' + [regex]::Escape($Key) + ':.*$')
    if ($keyPattern.Matches($block).Count -eq 1) {
        $block = $keyPattern.Replace($block, "      ${Key}: `"$Value`"", 1)
    } elseif ($keyPattern.Matches($block).Count -eq 0) {
        $environmentPattern = [regex]::new('(?m)^    environment:\r?$')
        if ($environmentPattern.Matches($block).Count -ne 1) {
            throw "Cannot uniquely locate environment block: $Service"
        }
        $block = $environmentPattern.Replace(
            $block,
            "    environment:`r`n      ${Key}: `"$Value`"",
            1
        )
    } else {
        throw "Duplicate environment key in ${Service}: $Key"
    }
    return $Text.Substring(0, $match.Index) + $block + $Text.Substring($match.Index + $match.Length)
}

function WaitHealthy([string]$Name, [string]$Image) {
    for ($i = 0; $i -lt 90; $i++) {
        $value = Container $Name
        if ($value.configuredImage -eq $Image -and $value.health -eq 'healthy') { return $value }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become healthy on $Image"
}

function AssertHermesIdle {
    $active = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_runs WHERE status IN ('queued','claimed','running','generating');"
    if ($LASTEXITCODE -ne 0 -or [int]($active.Trim()) -ne 0) { throw 'Hermes has active work; UI/API deployment stopped' }
}

if (-not (Test-Path $Archive -PathType Leaf)) { throw "Missing archive: $Archive" }
if (-not (Test-Path $live -PathType Leaf)) { throw "Missing production override: $live" }
if (Test-Path $receiptPath) { throw "Creative UI release is already complete: $receiptPath" }
if ("$(docker image ls -q $frontendTag | Select-Object -First 1)".Trim()) { throw "Immutable frontend image already exists: $frontendTag" }
if ("$(docker image ls -q $apiTag | Select-Object -First 1)".Trim()) { throw "Immutable Hermes API image already exists: $apiTag" }

AssertHermesIdle
$enabled = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_schedules WHERE enabled=true;"
if ($LASTEXITCODE -ne 0 -or [int]($enabled.Trim()) -ne 0) { throw 'Hermes schedule is enabled; UI/API deployment stopped' }

$mainFrontend = Container 'web-frontend-1'
$hermesFrontend = Container 'web-hermes-frontend-1'
$hermesApi = Container 'web-hermes-api-1'
$backend = Container 'web-backend-1'
$untouchedNames = @('web-backend-1', 'web-ai-worker-1', 'web-hermes-worker-1', 'web-postgres-1', 'web-redis-1', 'web-minio-1')
$untouched = @($untouchedNames | ForEach-Object { Container $_ })
$backup = Join-Path $release ('private\service-before-' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $source, $backup | Out-Null
Copy-Item $live (Join-Path $backup 'docker-compose.override.yml')
Copy-Item (Join-Path $ProjectRoot '.release\current.json') (Join-Path $backup 'core-current.json')
if (Test-Path (Join-Path $ProjectRoot '.release\hermes\current.json')) {
    Copy-Item (Join-Path $ProjectRoot '.release\hermes\current.json') (Join-Path $backup 'hermes-current.json')
}
Expand-Archive -Path $Archive -DestinationPath $source -Force

Set-Location $source
Exec {
    docker build --pull=false -f frontend/Dockerfile `
        --build-arg BACKEND_ORIGIN=http://backend:8000 `
        --build-arg HERMES_BACKEND_ORIGIN=http://hermes-api:8000 `
        --build-arg NEXT_PUBLIC_API_BASE=/api/backend `
        --build-arg NEXT_PUBLIC_APP_VERSION=$Version `
        --build-arg NEXT_PUBLIC_GIT_COMMIT=$Commit `
        --build-arg NEXT_PUBLIC_BUILD_TIME=$stamp `
        -t $frontendTag frontend
} 'Creative frontend image build failed'
Exec {
    docker build --pull=false -f scripts/windows/Dockerfile.hermes-api-release `
        --build-arg BASE_IMAGE=$($backend.configuredImage) `
        --build-arg APP_VERSION=$Version `
        --build-arg GIT_COMMIT=$Commit `
        --build-arg BUILD_TIME=$stamp `
        -t $apiTag .
} 'Hermes API image build failed'
Exec { docker run --rm --entrypoint python $apiTag -m compileall -q -f /app/app } 'Hermes API source compilation failed'

$raw = [IO.File]::ReadAllText($live)
if (-not $raw.Contains($hermesFrontend.configuredImage)) { throw 'Current Hermes frontend image is absent from the live override' }
if (-not $raw.Contains($hermesApi.configuredImage)) { throw 'Current Hermes API image is absent from the live override' }
$mainPattern = [regex]::new('(?m)^  frontend:\r?\n')
if ($mainPattern.Matches($raw).Count -ne 1) { throw 'Cannot uniquely locate the main frontend override block' }
$raw = $mainPattern.Replace(
    $raw,
    "  frontend:`r`n    image: $frontendTag`r`n    build: !reset null`r`n",
    1
)
$raw = $raw.Replace($hermesFrontend.configuredImage, $frontendTag)
$raw = $raw.Replace($hermesApi.configuredImage, $apiTag)
foreach ($service in @('frontend', 'hermes-frontend')) {
    $raw = SetServiceEnvironment $raw $service 'NEXT_PUBLIC_APP_VERSION' $Version
    $raw = SetServiceEnvironment $raw $service 'NEXT_PUBLIC_GIT_COMMIT' $Commit
    $raw = SetServiceEnvironment $raw $service 'NEXT_PUBLIC_BUILD_TIME' $stamp
}
$raw = SetServiceEnvironment $raw 'hermes-api' 'APP_VERSION' $Version
$raw = SetServiceEnvironment $raw 'hermes-api' 'GIT_COMMIT' $Commit
$raw = SetServiceEnvironment $raw 'hermes-api' 'BUILD_TIME' $stamp
[IO.File]::WriteAllText($candidate, $raw, $utf8)
Exec {
    docker compose --project-name web --project-directory $ProjectRoot `
        -f "$ProjectRoot\docker-compose.yml" -f $candidate --profile hermes config --quiet
} 'Candidate UI/API compose validation failed'

try {
    Exec { docker stop --timeout 30 web-frontend-1 web-hermes-frontend-1 } 'Frontend admission gate failed'
    AssertHermesIdle
    Exec { docker stop --timeout 60 web-hermes-api-1 } 'Hermes API stop failed'
    Copy-Item $candidate $live -Force
    Set-Location $ProjectRoot
    Exec {
        docker compose --profile hermes up -d --no-deps --no-build frontend hermes-frontend hermes-api
    } 'Creative UI/API cutover failed'

    $newMain = WaitHealthy 'web-frontend-1' $frontendTag
    $newHermesFrontend = WaitHealthy 'web-hermes-frontend-1' $frontendTag
    $newApi = WaitHealthy 'web-hermes-api-1' $apiTag

    $spec = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/openapi.json' -TimeoutSec 15
    $runPath = $spec.paths.PSObject.Properties['/api/v1/hermes-workflows/runs/{run_id}'].Value
    if (-not $runPath -or -not $runPath.delete) { throw 'Hermes delete endpoint is absent from the candidate API' }
    foreach ($url in @('http://127.0.0.1:3000/prompts', 'http://127.0.0.1:3101/workflows')) {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 15
        if ($response.StatusCode -ne 200) { throw "Frontend verification failed: $url" }
    }
    Exec {
        docker exec web-frontend-1 sh -lc "grep -q 'http://hermes-api:8000/api/v1/hermes-workflows' /app/.next/routes-manifest.json"
    } 'Main frontend is not bound to the Hermes API'

    foreach ($old in $untouched) {
        $now = Container $old.name
        if ($now.id -ne $old.id -or $now.image -ne $old.image -or $now.started -ne $old.started) {
            throw "Unexpected service change: $($old.name)"
        }
    }

    $worker = Container 'web-hermes-worker-1'
    $receipt = [ordered]@{
        version = $Version
        status = 'live-verified'
        deployedAt = [DateTime]::UtcNow.ToString('o')
        revision = $Commit
        scope = 'Stable homepage masonry, private workflow history, terminal task deletion, internal-only production references'
        serviceVersions = @{ frontend = $Version; api = $Version; worker = '0.3.30' }
        images = @{
            frontend = $newMain.image
            api = $newApi.image
            worker = $worker.image
        }
        sourceArchiveSha256 = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        scheduleEnabled = $false
        generationRequests = 0
        databaseMigration = $false
        acceptance = @{
            frontendsHealthy = $true
            apiHealthy = $true
            deleteEndpointPresent = $true
            hermesRewriteVerified = $true
            coreAndAiWorkersUntouched = $true
        }
        rollback = @{
            composeBackup = (Join-Path $backup 'docker-compose.override.yml')
            previousMainFrontend = $mainFrontend.configuredImage
            previousHermesFrontend = $hermesFrontend.configuredImage
            previousApi = $hermesApi.configuredImage
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
    docker compose --profile hermes up -d --no-deps --no-build frontend hermes-frontend hermes-api | Out-Host
    throw
}
