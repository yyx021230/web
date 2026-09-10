param(
    [string]$Version = '0.3.25',
    [string]$Archive = 'C:\projects\web\.release\incoming\hermes-compliance-0.3.25.zip'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$project = 'C:\projects\web'
$releaseRoot = 'D:\ztqc-hermes-release'
$release = Join-Path $releaseRoot $Version
$source = Join-Path $release 'source'
$oldSource = Join-Path $releaseRoot '0.3.22\source'
$live = Join-Path $project 'docker-compose.override.yml'
$candidate = Join-Path $release 'compose.candidate.yml'
$utf8 = New-Object Text.UTF8Encoding($false)

function Exec([scriptblock]$Action, [string]$Failure) {
    & $Action
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}
function Container([string]$Name) {
    $value = (docker inspect $Name | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $Name" }
    return @{name=$Name; id=$value.Id; image=$value.Image; started=$value.State.StartedAt}
}
function WaitHealthy([string]$Name, [string]$Image) {
    for ($i=0; $i -lt 90; $i++) {
        $value = (docker inspect $Name | ConvertFrom-Json)[0]
        if ($value.Config.Image -eq $Image -and $value.State.Health.Status -eq 'healthy') { return }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become healthy on $Image"
}

if (-not (Test-Path $Archive)) { throw "Missing archive: $Archive" }
if (-not (Test-Path $oldSource)) { throw "Missing verified 0.3.22 source baseline" }
if (Test-Path (Join-Path $release 'release-receipt.json')) { throw "Release is already complete: $release" }
if (-not (Test-Path $release)) { New-Item -ItemType Directory -Path $release | Out-Null }
if (-not (Test-Path $source)) { Copy-Item $oldSource $source -Recurse }
Expand-Archive -Path $Archive -DestinationPath $source -Force

$active = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_runs WHERE status IN ('queued','running');"
if ($LASTEXITCODE -ne 0 -or [int]($active.Trim()) -ne 0) { throw 'Hermes has queued/running work; deployment stopped' }
$enabled = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_schedules WHERE enabled=true;"
if ($LASTEXITCODE -ne 0 -or [int]($enabled.Trim()) -ne 0) { throw 'Hermes schedule is enabled; deployment stopped' }

$untouchedNames = @('web-backend-1','web-ai-worker-1','web-postgres-1','web-redis-1','web-minio-1')
$untouched = @($untouchedNames | ForEach-Object { Container $_ })
$backup = Join-Path $release ('private\service-before-' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $live (Join-Path $backup 'docker-compose.override.yml')
Copy-Item (Join-Path $project '.release\hermes\current.json') (Join-Path $backup 'hermes-current.json')
Copy-Item (Join-Path $project '.release\current.json') (Join-Path $backup 'core-current.json')

$stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
$frontendTag = "ztqc/frontend:$Version"
$apiTag = "ztqc/hermes-api:$Version"
$workerTag = "ztqc/hermes-worker:$Version"
Set-Location $source
$frontendImage = docker image ls -q $frontendTag
if (-not $frontendImage) {
    Exec { docker build --pull=false -f frontend/Dockerfile --build-arg BACKEND_ORIGIN=http://backend:8000 --build-arg HERMES_BACKEND_ORIGIN=http://hermes-api:8000 --build-arg NEXT_PUBLIC_API_BASE=/api/backend --build-arg NEXT_PUBLIC_APP_VERSION=$Version --build-arg NEXT_PUBLIC_GIT_COMMIT=policy-copy-guard-20260909 --build-arg NEXT_PUBLIC_BUILD_TIME=$stamp -t $frontendTag frontend } 'Frontend image build failed'
}
Exec { docker build --pull=false -f scripts/windows/Dockerfile.hermes-compliance-api --build-arg APP_VERSION=$Version --build-arg GIT_COMMIT=policy-copy-guard-20260909 --build-arg BUILD_TIME=$stamp -t $apiTag . } 'Hermes API image build failed'
$workerImage = docker image ls -q $workerTag
if (-not $workerImage) {
    Exec { docker build --pull=false -f scripts/windows/Dockerfile.hermes-compliance-worker --build-arg REVISION=policy-copy-guard-20260909 -t $workerTag . } 'Hermes Worker image build failed'
}

$raw = [IO.File]::ReadAllText($live)
foreach ($expected in @('ztqc/frontend:0.3.22','ztqc/hermes-api:0.3.22','ztqc/hermes-worker:0.3.24')) {
    if (-not $raw.Contains($expected)) { throw "Unexpected live compose; missing $expected" }
}
$raw = $raw.Replace('ztqc/frontend:0.3.22', $frontendTag)
$raw = $raw.Replace('ztqc/hermes-api:0.3.22', $apiTag)
$raw = $raw.Replace('ztqc/hermes-worker:0.3.24', $workerTag)
$raw = $raw.Replace('NEXT_PUBLIC_APP_VERSION: "0.3.22"', "NEXT_PUBLIC_APP_VERSION: `"$Version`"")
$raw = $raw.Replace('APP_VERSION: "0.3.22"', "APP_VERSION: `"$Version`"")
$raw = $raw.Replace('HERMES_POLICY_CASES_PATH: /app/hermes-config/cases.json', "HERMES_POLICY_CASES_PATH: /app/hermes-config/cases.json`r`n      HERMES_POLICY_DISPLAY_PATH: /app/hermes-config/policy_display.json")
[IO.File]::WriteAllText($candidate, $raw, $utf8)
Exec { docker compose --project-name web --project-directory $project -f "$project\docker-compose.yml" -f $candidate --profile hermes config --quiet } 'Candidate compose validation failed'

Exec { docker stop --timeout 2700 web-hermes-worker-1 } 'Worker drain failed'
Exec { docker run --rm --network none --entrypoint python --mount "type=bind,source=$release,target=/release" --mount 'type=volume,source=web_hermes-config,target=/live/config' --mount 'type=volume,source=web_hermes-home,target=/live/home' $workerTag /release/source/scripts/windows/install_hermes_compliance.py --execute } 'Policy/plugin installation failed'
Copy-Item $candidate $live -Force
Set-Location $project
Exec { docker compose --profile hermes up -d --no-deps --no-build frontend hermes-frontend hermes-api } 'Frontend/API switch failed'
WaitHealthy 'web-frontend-1' $frontendTag
WaitHealthy 'web-hermes-frontend-1' $frontendTag
WaitHealthy 'web-hermes-api-1' $apiTag
Exec { docker compose --profile hermes up -d --no-deps --no-build hermes-worker } 'Worker switch failed'
WaitHealthy 'web-hermes-worker-1' $workerTag
Exec { docker run --rm --network none --entrypoint python --mount "type=bind,source=$release,target=/release,readonly" --mount 'type=volume,source=web_hermes-config,target=/live/config,readonly' --mount 'type=volume,source=web_hermes-home,target=/live/home,readonly' $workerTag /release/source/scripts/windows/install_hermes_compliance.py --verify } 'Live policy/plugin verification failed'

$policyCheck = docker exec web-hermes-api-1 python -c "from app.services.hermes_policy_service import policy_summaries; r={x['case_id']:x for x in policy_summaries()}; a=r['a05-current']['quote_rows'][0]; assert a['official_guide_price']=='¥63,900' and a['national_scrappage_after_price']=='¥56,232' and a['provincial_trade_in_after_price']=='¥58,788'; print(len(r))"
if ($LASTEXITCODE -ne 0 -or [int]($policyCheck.Trim()) -ne 11) { throw 'Hermes API policy display verification failed' }
foreach ($target in @('http://127.0.0.1:3000/','http://127.0.0.1:3101/','http://127.0.0.1:8001/health/ready')) {
    $status = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 $target).StatusCode
    if ($status -ne 200) { throw "HTTP verification failed: $target" }
}
foreach ($old in $untouched) {
    $now = Container $old.name
    if ($now.id -ne $old.id -or $now.image -ne $old.image -or $now.started -ne $old.started) { throw "Unexpected service change: $($old.name)" }
}

$receipt = @{
    version=$Version; status='live-verified'; deployedAt=[DateTime]::UtcNow.ToString('o'); revision='policy-copy-guard-20260909';
    serviceVersions=@{frontend=$Version; api=$Version; worker=$Version}; scheduleEnabled=$false; generationRequests=0;
    scope='National/provincial subsidy terminology; province price UI-only; no image lead-generation wording';
    images=@{frontend=(docker image inspect $frontendTag --format '{{.Id}}'); api=(docker image inspect $apiTag --format '{{.Id}}'); worker=(docker image inspect $workerTag --format '{{.Id}}')};
    sourceArchiveSha256=(Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower(); composeBackup=(Join-Path $backup 'docker-compose.override.yml');
    acceptance=@{servicesHealthy=$true; untouchedCoreServices=$true; apiPolicyCases=11; provinceAmountsHiddenFromProduction=$true; displayRowsSeparated=$true; retiredWordingRejected=$true; imageLeadWordingRejected=$true};
    rollback=@{composeBackup=(Join-Path $backup 'docker-compose.override.yml'); policyBackup=(Get-Content (Join-Path $release 'policy-install.json') -Raw | ConvertFrom-Json).backup; databaseRestore=$false}
}
$json = $receipt | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText((Join-Path $release 'release-receipt.json'), $json, $utf8)
[IO.File]::WriteAllText((Join-Path $project '.release\hermes\current.json'), $json, $utf8)
$corePath = Join-Path $project '.release\current.json'
$core = Get-Content $corePath -Raw | ConvertFrom-Json
$core.hermesRelease.version = $Version
[IO.File]::WriteAllText($corePath, ($core | ConvertTo-Json -Depth 20), $utf8)
Write-Output ($receipt | ConvertTo-Json -Depth 20 -Compress)
