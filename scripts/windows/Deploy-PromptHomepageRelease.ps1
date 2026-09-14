param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Commit,
    [Parameter(Mandatory = $true)][string]$Archive,
    [string]$ProjectRoot = 'C:\projects\web'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$releaseRoot = 'D:\ztqc-hermes-release'
$release = Join-Path $releaseRoot "$Version-homepage"
$source = Join-Path $release 'source'
$live = Join-Path $ProjectRoot 'docker-compose.override.yml'
$candidate = Join-Path $release 'compose.candidate.yml'
$receiptPath = Join-Path $release 'release-receipt.json'
$utf8 = New-Object Text.UTF8Encoding($false)
$stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$frontendTag = "ztqc/frontend:$Version-$Commit-homepage"

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

if (-not (Test-Path $Archive -PathType Leaf)) { throw "Missing archive: $Archive" }
if (-not (Test-Path $live -PathType Leaf)) { throw "Missing production override: $live" }
if (Test-Path $receiptPath) { throw "Homepage release is already complete: $receiptPath" }
if ("$(docker image ls -q $frontendTag | Select-Object -First 1)".Trim()) { throw "Immutable frontend image already exists: $frontendTag" }

$mainFrontend = Container 'web-frontend-1'
$hermesFrontend = Container 'web-hermes-frontend-1'
if ($mainFrontend.configuredImage -ne $hermesFrontend.configuredImage) {
    throw 'Main and Hermes frontends are not on the same reviewed baseline image'
}
$untouchedNames = @(
    'web-backend-1',
    'web-ai-worker-1',
    'web-hermes-api-1',
    'web-hermes-worker-1',
    'web-postgres-1',
    'web-redis-1',
    'web-minio-1'
)
$untouched = @($untouchedNames | ForEach-Object { Container $_ })
$backup = Join-Path $release ('private\service-before-' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $source, $backup | Out-Null
Copy-Item $live (Join-Path $backup 'docker-compose.override.yml')
Copy-Item (Join-Path $ProjectRoot '.release\current.json') (Join-Path $backup 'core-current.json')
Copy-Item (Join-Path $ProjectRoot '.release\hermes\current.json') (Join-Path $backup 'hermes-current.json')
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
} 'Homepage frontend image build failed'

$raw = [IO.File]::ReadAllText($live)
$oldImage = $mainFrontend.configuredImage
$oldImageCount = ([regex]::Matches($raw, [regex]::Escape($oldImage))).Count
if ($oldImageCount -ne 2) { throw "Expected the reviewed frontend image twice, found $oldImageCount occurrences" }
$raw = $raw.Replace($oldImage, $frontendTag)
foreach ($service in @('frontend', 'hermes-frontend')) {
    $raw = SetServiceEnvironment $raw $service 'NEXT_PUBLIC_APP_VERSION' $Version
    $raw = SetServiceEnvironment $raw $service 'NEXT_PUBLIC_GIT_COMMIT' $Commit
    $raw = SetServiceEnvironment $raw $service 'NEXT_PUBLIC_BUILD_TIME' $stamp
}
[IO.File]::WriteAllText($candidate, $raw, $utf8)
Exec {
    docker compose --project-name web --project-directory $ProjectRoot `
        -f "$ProjectRoot\docker-compose.yml" -f $candidate --profile hermes config --quiet
} 'Candidate homepage compose validation failed'

try {
    Exec { docker stop --timeout 30 web-frontend-1 web-hermes-frontend-1 } 'Frontend admission gate failed'
    Copy-Item $candidate $live -Force
    Set-Location $ProjectRoot
    Exec {
        docker compose --profile hermes up -d --no-deps --no-build frontend hermes-frontend
    } 'Homepage frontend cutover failed'

    $newMain = WaitHealthy 'web-frontend-1' $frontendTag
    $newHermes = WaitHealthy 'web-hermes-frontend-1' $frontendTag
    foreach ($url in @('http://127.0.0.1:3000/prompts', 'http://127.0.0.1:3101/prompts')) {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 20
        if ($response.StatusCode -ne 200) { throw "Homepage verification failed: $url" }
    }
    Exec {
        docker exec web-frontend-1 sh -lc "grep -R -q 'creative-studio.local' /app/.next/server /app/.next/static"
    } 'Homepage deduplication marker is absent from the candidate frontend'

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
        scope = 'Prompt detail image fitting and infinite-scroll visual deduplication'
        serviceVersions = @{
            frontend = $Version
            api = $untouched.Where({ $_.name -eq 'web-hermes-api-1' })[0].configuredImage
            worker = $untouched.Where({ $_.name -eq 'web-hermes-worker-1' })[0].configuredImage
        }
        images = @{
            mainFrontend = $newMain.image
            hermesFrontend = $newHermes.image
        }
        sourceArchiveSha256 = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        generationRequests = 0
        databaseMigration = $false
        acceptance = @{
            frontendsHealthy = $true
            homepageMarkerPresent = $true
            APIsWorkersAndDataServicesUntouched = $true
        }
        rollback = @{
            composeBackup = (Join-Path $backup 'docker-compose.override.yml')
            previousMainFrontend = $mainFrontend.configuredImage
            previousHermesFrontend = $hermesFrontend.configuredImage
            databaseRestore = $false
        }
    }
    $json = $receipt | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($receiptPath, $json, $utf8)

    $hermesPath = Join-Path $ProjectRoot '.release\hermes\current.json'
    $hermes = Get-Content $hermesPath -Raw | ConvertFrom-Json
    $hermes.version = $Version
    $hermes.status = 'live-verified'
    $hermes.deployedAt = $receipt.deployedAt
    $hermes.revision = $Commit
    $hermes.serviceVersions.frontend = $Version
    $hermes.images.frontend = $newMain.image
    $hermes | Add-Member -NotePropertyName homepageRelease -NotePropertyValue @{ version = $Version; receipt = $receiptPath } -Force
    [IO.File]::WriteAllText($hermesPath, ($hermes | ConvertTo-Json -Depth 20), $utf8)

    $corePath = Join-Path $ProjectRoot '.release\current.json'
    $core = Get-Content $corePath -Raw | ConvertFrom-Json
    $pointer = @{ version = $Version; receipt = $receiptPath }
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
    docker compose --profile hermes up -d --no-deps --no-build frontend hermes-frontend | Out-Host
    throw
}
