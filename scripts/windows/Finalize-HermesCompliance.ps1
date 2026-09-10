param([string]$Version = '0.3.25')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$project = 'C:\projects\web'
$release = "D:\ztqc-hermes-release\$Version"
$archive = "$project\.release\incoming\hermes-compliance-0.3.25.zip"
$utf8 = New-Object Text.UTF8Encoding($false)

function Container([string]$Name) {
    $value = (docker inspect $Name | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $Name" }
    return @{name=$Name; id=$value.Id; image=$value.Image; started=$value.State.StartedAt; health=$value.State.Health.Status; configuredImage=$value.Config.Image}
}
function RequireHealthy([string]$Name, [string]$Tag) {
    for ($i=0; $i -lt 60; $i++) {
        $value = Container $Name
        if ($value.configuredImage -eq $Tag -and $value.health -eq 'healthy') { return $value }
        Start-Sleep -Seconds 2
    }
    throw "$Name is not healthy on $Tag"
}

$frontend = RequireHealthy 'web-frontend-1' "ztqc/frontend:$Version"
$hermesFrontend = RequireHealthy 'web-hermes-frontend-1' "ztqc/frontend:$Version"
$api = RequireHealthy 'web-hermes-api-1' "ztqc/hermes-api:$Version"
$worker = RequireHealthy 'web-hermes-worker-1' "ztqc/hermes-worker:$Version"

$verify = docker run --rm --network none --entrypoint python --mount "type=bind,source=$release,target=/release,readonly" --mount 'type=volume,source=web_hermes-config,target=/live/config,readonly' --mount 'type=volume,source=web_hermes-home,target=/live/home,readonly' "ztqc/hermes-worker:$Version" /release/source/scripts/windows/install_hermes_compliance.py --verify
if ($LASTEXITCODE -ne 0) { throw 'Policy, plugin or Worker runtime verification failed' }
$policyCheck = docker exec web-hermes-api-1 python -c "import re; from app.services.hermes_policy_service import policy_summaries; r={x['case_id']:x for x in policy_summaries()}; a=r['a05-current']['quote_rows'][0]; assert [re.sub(r'[^0-9]','',a[k]) for k in ('official_guide_price','national_scrappage_after_price','provincial_trade_in_after_price')]==['63900','56232','58788']; print(len(r))"
if ($LASTEXITCODE -ne 0 -or [int]($policyCheck.Trim()) -ne 11) { throw 'API display policy verification failed' }
foreach ($target in @('http://127.0.0.1:3000/','http://127.0.0.1:3101/','http://127.0.0.1:8001/health/ready')) {
    if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 $target).StatusCode -ne 200) { throw "HTTP verification failed: $target" }
}
$active = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_runs WHERE status IN ('queued','running');"
$enabled = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_schedules WHERE enabled=true;"
if ($LASTEXITCODE -ne 0 -or [int]($active.Trim()) -ne 0 -or [int]($enabled.Trim()) -ne 0) { throw 'Task/schedule post-check failed' }

$previous = Get-Content 'D:\ztqc-hermes-release\0.3.24\release-receipt.json' -Raw | ConvertFrom-Json
$coreNames = @('web-backend-1','web-ai-worker-1','web-postgres-1','web-redis-1','web-minio-1')
foreach ($name in $coreNames) {
    $old = @($previous.untouched | Where-Object { $_.name -eq $name })[0]
    $now = Container $name
    if (-not $old -or $now.id -ne $old.id -or $now.image -ne $old.image -or $now.started -ne $old.started) { throw "Core service changed: $name" }
}
$compose = docker compose --project-name web --project-directory $project -f "$project\docker-compose.yml" -f "$project\docker-compose.override.yml" --profile hermes config --format json | ConvertFrom-Json
if ($compose.services.frontend.image -ne "ztqc/frontend:$Version" -or $compose.services.'hermes-frontend'.image -ne "ztqc/frontend:$Version" -or $compose.services.'hermes-api'.image -ne "ztqc/hermes-api:$Version" -or $compose.services.'hermes-worker'.image -ne "ztqc/hermes-worker:$Version") { throw 'Resolved Compose image mismatch' }
if ($compose.services.'hermes-api'.environment.HERMES_POLICY_DISPLAY_PATH -ne '/app/hermes-config/policy_display.json') { throw 'Display policy path is not configured' }

$receipt = @{
    version=$Version; status='live-verified'; deployedAt=[DateTime]::UtcNow.ToString('o'); revision='policy-copy-guard-20260909';
    serviceVersions=@{frontend=$Version; api=$Version; worker=$Version}; images=@{frontend=$frontend.image; api=$api.image; worker=$worker.image};
    scope='National/provincial subsidy terminology; province price UI-only; no image lead-generation wording';
    sourceArchiveSha256=(Get-FileHash $archive -Algorithm SHA256).Hash.ToLower(); scheduleEnabled=$false; generationRequests=0;
    acceptance=@{servicesHealthy=$true; lanHttp=$true; apiPolicyCases=11; productionProvinceAmountsHidden=$true; displayRowsSeparated=$true; retiredWordingAbsent=$true; imageLeadWordingGuarded=$true; workerRuntimeMatchesRelease=$true; untouchedCoreServices=$true};
    verification=($verify -join "`n"); previousRelease='0.3.24'; databaseMigration=$false; databaseRestore=$false;
    rollback=@{composeBackup='D:\ztqc-hermes-release\0.3.25\private\service-before-20260909_172538\docker-compose.override.yml'; policyBackup='D:\ztqc-hermes-release\0.3.25\private\policy-copy-before-20260909T092450Z'; databaseRestore=$false}
}
$json = $receipt | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText("$release\release-receipt.json", $json, $utf8)
[IO.File]::WriteAllText("$project\.release\hermes\current.json", $json, $utf8)
$corePath = "$project\.release\current.json"
$core = Get-Content $corePath -Raw | ConvertFrom-Json
$core.hermesRelease.version = $Version
[IO.File]::WriteAllText($corePath, ($core | ConvertTo-Json -Depth 20), $utf8)
Write-Output ($receipt | ConvertTo-Json -Depth 20 -Compress)
