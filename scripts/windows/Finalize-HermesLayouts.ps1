$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$release = 'D:\ztqc-hermes-release\0.3.21'
$project = 'C:\projects\web'
$utf8 = New-Object Text.UTF8Encoding($false)
$record = Get-Content "$release\release-receipt.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.version -ne '0.3.21' -or (Get-FileHash "$project\docker-compose.override.yml").Hash -ne $record.candidateHash) { throw 'Unexpected current release' }
foreach ($service in @('frontend','hermes-frontend','hermes-api','hermes-worker')) {
    $c = (docker inspect "web-$service-1" | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0 -or $c.Image -ne $record.images.$service -or $c.State.Health.Status -ne 'healthy') { throw "Unexpected image/health: $service" }
}
$head = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c 'SELECT version_num FROM alembic_version;'
if ($LASTEXITCODE -ne 0 -or $head.Trim() -ne 'c3d4e5f6a7b8') { throw 'Unexpected database head' }
$result = docker exec -e PYTHONPATH=/app web-hermes-api-1 python /tmp/accept_hermes_layouts.py
if ($LASTEXITCODE -ne 0) { throw 'Cannot read content acceptance status' }
$accept = ($result -join "`n") | ConvertFrom-Json
$complete = @($accept.runs).Count -eq 2
foreach ($run in $accept.runs) {
    if ($run.status -ne 'review_pending' -or $run.generated_posts -ne 1 -or $run.posts[0].hard_pass -ne $true -or $run.posts[0].publish_status -ne 'not_requested' -or $run.posts[0].selected_prompt_id -ne $run.expected_mother_id) { $complete = $false }
}
if ($accept.schedule_enabled) { throw 'Unexpected enabled schedule' }
$record.status = if ($complete) {'live-functional-pass-content-review-required'} else {'live-content-acceptance-pending'}
foreach ($item in @{
    verifiedAt=[DateTime]::UtcNow.ToString('o'); databaseHead=$head.Trim();
    publicUrl='http://47.98.127.132:18080'; windowsUrl='http://192.168.10.107:3000';
    regressionTests=@{production=178;api=36;frontend=41;total=255;typescript='passed';imageFixtureCases=34};
    acceptance=$accept;functionalAcceptancePassed=$complete;contentAcceptancePassed=$false;backupsCopiedToMac=$false;
    openContentIssues=@(@{runId=3;kind='non-equivalent-image-slot-substitution';
        evidence='Source suspension slot became campaign deadline; dimensions became brand label.';
        status='reported-to-user-awaiting-rule-change-approval';productionRulesChanged=$false});
    rollback=@{imagesVersion='0.3.20';composeBackup="$($record.backup)\docker-compose.override.yml";databaseRestore=$false;requiresWorkerDrain=$true};
    limits=@('Two precise single samples, not a 40-post throughput or long-term success-rate guarantee','Existing created-time UTC/CST display offset is unchanged')
}.GetEnumerator()) { $record | Add-Member -NotePropertyName $item.Key -NotePropertyValue $item.Value -Force }
[IO.File]::WriteAllText("$release\content-acceptance.json", ($result -join "`n"), $utf8)
$json = $record | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText("$release\release-receipt.json", $json, $utf8)
[IO.File]::WriteAllText("$project\.release\hermes\current.json", $json, $utf8)
$core = Get-Content "$project\.release\current.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if ($core.version -ne '0.3.18') { throw 'Core version is not expected 0.3.18; module receipt saved only' }
$core.activeFrontend.version = '0.3.21'
$core.hermesRelease.version = '0.3.21'
$local = (docker inspect web-frontend-1 | ConvertFrom-Json)[0]
$core.localFrontend = @{
    version='0.3.21'; target='web-frontend-1'; url='http://192.168.10.107:3000/workflows';
    image=$record.images.frontend; containerId=$local.Id; startedAt=$local.State.StartedAt;
    verifiedAt=$record.verifiedAt; status='entry-verified'; overrideHash=$record.candidateHash;
    backupDir=$record.backup; receipt="$project\.release\hermes\current.json"
}
[IO.File]::WriteAllText("$project\.release\current.json", ($core | ConvertTo-Json -Depth 20), $utf8)
@{moduleVersion=$record.version;status=$record.status;functionalAcceptancePassed=$complete;contentAcceptancePassed=$false;coreVersion=$core.version;receipt="$project\.release\hermes\current.json"} | ConvertTo-Json
