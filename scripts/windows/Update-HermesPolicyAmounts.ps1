param([switch]$Execute)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$project='C:\projects\web'
$release='D:\ztqc-hermes-release\0.3.24'
$live="$project\docker-compose.override.yml"
$candidate="$release\compose.candidate.yml"
$tag='ztqc/hermes-worker:0.3.24'
$utf8=New-Object Text.UTF8Encoding($false)
function Json($value){return ConvertTo-Json -InputObject $value -Depth 100 -Compress}
function Save($path,$value){[IO.File]::WriteAllText($path,(Json $value),$utf8)}
function Config($path){
    $raw=docker compose --project-name web --project-directory $project -f "$project\docker-compose.yml" -f $path --profile hermes config --format json
    if($LASTEXITCODE -ne 0){throw 'Compose validation failed'}
    return (($raw -join "`n")|ConvertFrom-Json)
}
function Snapshot($name){
    $c=(docker inspect $name|ConvertFrom-Json)[0]
    if($LASTEXITCODE -ne 0){throw "Cannot inspect $name"}
    return @{name=$name;id=$c.Id;image=$c.Image;started=$c.State.StartedAt;running=$c.State.Running}
}
function Installer([string]$mode){
    $arguments=@('run','--rm','--network','none','--entrypoint','python','-e','PYTHONPATH=/app/web/ops/xhs_hermes',
        '--mount',"type=bind,source=$release,target=/release",
        '--mount','type=volume,source=web_hermes-config,target=/live/config',
        '--mount','type=volume,source=web_hermes-state,target=/live/state',
        $tag,'/release/install_hermes_policy_amounts.py')
    if($mode){$arguments+=$mode}
    & docker @arguments
    if($LASTEXITCODE -ne 0){throw 'Policy file installation/check failed; inspect retained backup before continuing'}
}
$beforeHash=(Get-FileHash $live).Hash
$raw=[IO.File]::ReadAllText($live)
if(([regex]::Matches($raw,'ztqc/hermes-worker:0\.3\.23')).Count -ne 1){throw 'Unexpected existing Worker image'}
[IO.File]::WriteAllText($candidate,$raw.Replace('ztqc/hermes-worker:0.3.23',$tag),$utf8)
$before=Config $live
$after=Config $candidate
if($after.services.'hermes-worker'.image -ne $tag){throw 'Wrong candidate Worker'}
$before.services.'hermes-worker'.PSObject.Properties.Remove('image')
$after.services.'hermes-worker'.PSObject.Properties.Remove('image')
if((Json $before) -cne (Json $after)){throw 'Unexpected changes beyond the Worker image'}
$image=(docker image inspect $tag|ConvertFrom-Json)[0]
if($LASTEXITCODE -ne 0 -or $image.Config.Labels.'org.opencontainers.image.revision' -ne 'policy-amounts-20260909'){throw 'Wrong candidate build'}
Installer ''
$names=@('web-frontend-1','web-hermes-frontend-1','web-hermes-api-1','web-backend-1','web-ai-worker-1','web-postgres-1','web-redis-1','web-minio-1')
$baseline=@($names|ForEach-Object{Snapshot $_})
$record=@{version='0.3.24';scope='approved-local-policy-amounts-only';candidateHash=(Get-FileHash $candidate).Hash;
    oldOverrideHash=$beforeHash;workerImage=$image.Id;untouched=$baseline;generationRequests=0}
Save "$release\preflight.json" $record
if(-not $Execute){Write-Output 'Policy release preflight passed; no service or policy switched';exit 0}
$active=docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c "SELECT count(*) FROM hermes_workflow_runs WHERE status IN ('queued','running');"
if($LASTEXITCODE -ne 0 -or [int]($active.Trim()) -ne 0){throw 'Production task present; leave it running and wait before switching policy'}
$backup=Join-Path $release ('private\service-before-'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup|Out-Null
Copy-Item $live "$backup\docker-compose.override.yml"
Copy-Item "$project\.release\current.json" "$backup\core-current.json"
Copy-Item "$project\.release\hermes\current.json" "$backup\hermes-current.json"
$record.serviceBackup=$backup
Save "$release\deployment-started.json" $record
docker stop --timeout 2700 web-hermes-worker-1
if($LASTEXITCODE -ne 0){throw 'Worker drain failed; policy unchanged'}
if((Get-FileHash $live).Hash -ne $beforeHash){throw 'Compose changed during drain; stop for review'}
Installer '--execute'
Copy-Item $candidate $live -Force
Set-Location $project
cmd /c "docker compose --profile hermes up -d --no-deps --no-build hermes-worker > $release\switch.log 2>&1"
if($LASTEXITCODE -ne 0){throw 'Worker reload failed; inspect switch.log'}
$healthy=$false
for($i=0;$i -lt 60;$i++){
    $c=(docker inspect web-hermes-worker-1|ConvertFrom-Json)[0]
    if($c.Image -eq $image.Id -and $c.State.Health.Status -eq 'healthy'){$healthy=$true;break}
    Start-Sleep -Seconds 2
}
if(-not $healthy){throw 'New Worker did not become healthy; backup retained'}
Installer '--verify'
foreach($old in $baseline){if((Json (Snapshot $old.name)) -cne (Json $old)){throw "Unexpected service change: $($old.name)"}}
$record.status='live-awaiting-api-verification'
$record.deployedAt=[DateTime]::UtcNow.ToString('o')
Save "$release\release-receipt.json" $record
Write-Output (Json $record)
