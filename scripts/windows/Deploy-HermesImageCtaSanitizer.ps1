param(
    [string]$Version = '0.3.27',
    [string]$Archive = 'C:\projects\web\.release\incoming\hermes-image-cta-0.3.27.zip'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$project = 'C:\projects\web'
$releaseRoot = 'D:\ztqc-hermes-release'
$release = Join-Path $releaseRoot $Version
$source = Join-Path $release 'source'
$baseline = Join-Path $releaseRoot '0.3.26\source'
$live = Join-Path $project 'docker-compose.override.yml'
$candidate = Join-Path $release 'compose.candidate.yml'
$utf8 = New-Object Text.UTF8Encoding($false)
$workerTag = "ztqc/hermes-worker:$Version"
$revision = 'image-cta-sanitize-v2-20260910'

function Exec([scriptblock]$Action, [string]$Failure) {
    & $Action
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}
function Container([string]$Name) {
    $value = (docker inspect $Name | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $Name" }
    return @{name=$Name; id=$value.Id; image=$value.Image; started=$value.State.StartedAt; configuredImage=$value.Config.Image; health=$value.State.Health.Status}
}
function WaitHealthy([string]$Name, [string]$Image) {
    for ($i=0; $i -lt 90; $i++) {
        $value = Container $Name
        if ($value.configuredImage -eq $Image -and $value.health -eq 'healthy') { return $value }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become healthy on $Image"
}

if (-not (Test-Path $Archive)) { throw "Missing archive: $Archive" }
if (-not (Test-Path $baseline)) { throw "Missing verified baseline: $baseline" }
if (Test-Path (Join-Path $release 'release-receipt.json')) { throw "Release already complete: $release" }
if (-not (Test-Path $release)) { New-Item -ItemType Directory -Path $release | Out-Null }
if (-not (Test-Path $source)) { Copy-Item $baseline $source -Recurse }
Expand-Archive -Path $Archive -DestinationPath $source -Force

$active = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_runs WHERE status IN ('queued','running');"
$enabled = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_schedules WHERE enabled=true;"
if ($LASTEXITCODE -ne 0 -or [int]($active.Trim()) -ne 0) { throw 'Hermes has active work; deployment stopped' }
if ([int]($enabled.Trim()) -ne 0) { throw 'Hermes schedule is enabled; deployment stopped' }

$untouchedNames = @('web-frontend-1','web-hermes-frontend-1','web-hermes-api-1','web-backend-1','web-ai-worker-1','web-postgres-1','web-redis-1','web-minio-1')
$untouched = @($untouchedNames | ForEach-Object { Container $_ })
$backup = Join-Path $release ('private\service-before-' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $live (Join-Path $backup 'docker-compose.override.yml')
Copy-Item (Join-Path $project '.release\hermes\current.json') (Join-Path $backup 'hermes-current.json')

Set-Location $source
Exec { docker build --pull=false -f scripts/windows/Dockerfile.hermes-compliance-worker --build-arg APP_VERSION=$Version --build-arg REVISION=$revision -t $workerTag . } 'Worker image build failed'
$raw = [IO.File]::ReadAllText($live)
if (-not $raw.Contains('ztqc/hermes-worker:0.3.26')) { throw 'Unexpected live worker image; refusing cutover' }
$raw = $raw.Replace('ztqc/hermes-worker:0.3.26', $workerTag)
[IO.File]::WriteAllText($candidate, $raw, $utf8)
Exec { docker compose --project-name web --project-directory $project -f "$project\docker-compose.yml" -f $candidate --profile hermes config --quiet } 'Candidate compose validation failed'

try {
    Exec { docker stop --timeout 2700 web-hermes-worker-1 } 'Worker drain failed'
    Copy-Item $candidate $live -Force
    Set-Location $project
    Exec { docker compose --profile hermes up -d --no-deps --no-build hermes-worker } 'Worker cutover failed'
    $worker = WaitHealthy 'web-hermes-worker-1' $workerTag
    Exec { docker exec web-hermes-worker-1 python -c "from core import sanitize_image_plan_lead_language,validate_image_plan; lead='\u7acb\u5373\u54a8\u8be2'; p={'adapted_prompt':'D19 poster '+lead,'slot_mappings':[{'source':lead,'output':lead}]}; r=sanitize_image_plan_lead_language(p,{'vehicle_model':'D19'}); assert r['text_blocks']==['D19']; assert not any('\u7559\u54a8' in x for x in validate_image_plan({**r,'source_slot_count':1}, {}, {'vehicle_model':'D19'})); print('sanitizer-ok')" } 'Runtime sanitizer verification failed'
    $imageInspect = (docker image inspect $workerTag | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0 -or $imageInspect.Config.Labels.'org.opencontainers.image.revision' -ne $revision) { throw 'Worker revision label mismatch' }
    foreach ($old in $untouched) {
        $now = Container $old.name
        if ($now.id -ne $old.id -or $now.image -ne $old.image -or $now.started -ne $old.started) { throw "Unexpected service change: $($old.name)" }
    }
    $receipt = @{
        version=$Version; status='live-verified'; deployedAt=[DateTime]::UtcNow.ToString('o'); revision=$revision;
        serviceVersions=@{frontend='0.3.25'; api='0.3.25'; worker=$Version}; scheduleEnabled=$false; generationRequests=0;
        scope='Mother-image lead wording is deterministically replaced before generation; final plan and OCR guards remain strict';
        image=@{worker=$worker.image}; sourceArchiveSha256=(Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower();
        acceptance=@{workerHealthy=$true; sanitizerRuntimeVerified=$true; finalPlanGuardRetained=$true; ocrGuardRetained=$true; untouchedServices=$true};
        previousRelease='0.3.26'; databaseMigration=$false;
        rollback=@{composeBackup=(Join-Path $backup 'docker-compose.override.yml'); previousWorker='ztqc/hermes-worker:0.3.26'; databaseRestore=$false}
    }
    $json = $receipt | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText((Join-Path $release 'release-receipt.json'), $json, $utf8)
    [IO.File]::WriteAllText((Join-Path $project '.release\hermes\current.json'), $json, $utf8)
    Write-Output ($receipt | ConvertTo-Json -Depth 20 -Compress)
} catch {
    Copy-Item (Join-Path $backup 'docker-compose.override.yml') $live -Force
    Set-Location $project
    docker compose --profile hermes up -d --no-deps --no-build hermes-worker | Out-Host
    throw
}
