$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$project='C:\projects\web'
$release='D:\ztqc-hermes-release\0.3.22'
$utf8=New-Object Text.UTF8Encoding($false)
function Save($path,$value) { [IO.File]::WriteAllText($path, ($value | ConvertTo-Json -Depth 30), $utf8) }
$record=Get-Content "$release\release-receipt.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$after=Get-Content "$release\catalog-after.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$import=Get-Content "$release\catalog-import.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$worker=Get-Content "$release\catalog-worker.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$repeat=Get-Content "$release\catalog-repeat-dry-run.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.version -ne '0.3.22' -or (Get-FileHash "$project\docker-compose.override.yml").Hash -ne $record.candidateHash) { throw 'Unexpected current release' }
foreach ($service in @('frontend','hermes-frontend','hermes-api','hermes-worker')) {
    $c=(docker inspect "web-$service-1" | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0 -or $c.Image -ne $record.images.$service -or $c.State.Health.Status -ne 'healthy') { throw "Wrong image/health: $service" }
}
if (-not $after.old_rows_unchanged -or -not $after.policy_unchanged -or $import.new -ne 106 -or $import.reused -ne 2 -or $repeat.new -ne 0 -or $repeat.reused -ne 108 -or $worker.live_library_count -ne 631 -or @($worker.preview_production_count_differences).Count -ne 0) { throw 'Acceptance evidence does not match' }
$previous=Get-Content "$($record.backup)\hermes-current.json" -Raw -Encoding UTF8 | ConvertFrom-Json
# Never label the separate core release as upgraded. Record observed runtime too,
# because its saved release metadata may predate an independent restore.
$core=Get-Content "$project\.release\current.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeCore=(docker inspect web-backend-1 | ConvertFrom-Json)[0].Config.Image
$acceptance=@{imported=106;reused=2;approved=108;existingReclassified=525;library=631;
    representativeLayouts=572;browsableExamples=571;types=8;oldRowsUnchanged=$true;policyUnchanged=$true;
    generationRequests=0;worker=$worker;catalog=$after.catalog_user_1.types;
    publicBrowser='verified 0.3.22, eight types, originals and pagination';
    windowsBrowser='verified 0.3.22, eight types, original examples and data-dependent guard';
    scope='Catalog/selection/static validation only; no new image generation or content-quality acceptance'}
foreach ($item in @{
    status='live-catalog-and-selection-verified';verifiedAt=[DateTime]::UtcNow.ToString('o');
    publicUrl='http://47.98.127.132:18080';windowsUrl='http://192.168.10.107:3000';
    regressionTests=@{production=361;apiImportWorkflows=38;apiLifecycleSecurity=27;frontend=61;total=487;typescript='passed'};
    acceptance=$acceptance;registrySha256=$after.registry_sha256;
    coreRecordedVersion=$core.version;coreRuntimeImage=$runtimeCore;coreChangedByRelease=$false;
    carriedForwardContentIssues=$previous.openContentIssues;
    rollback=@{workflowImagesVersion='0.3.21';composeBackup="$($record.backup)\docker-compose.override.yml";databaseRestore=$false;requiresWorkerDrain=$true;note='Imported records are additive; if reverting before catalog compatibility, suspend only imported IDs after checking references, never restore the entire database.'};
    limits=@('Layout contact-sheet review is not historical price/policy verification','400 statically admitted candidates with complete quote data are not 400 guaranteed generation passes','Public originals are large and first loads can be slower than cached loads');
    backupsCopiedToMac=$false
}.GetEnumerator()) { $record | Add-Member -NotePropertyName $item.Key -NotePropertyValue $item.Value -Force }
Save "$release\release-receipt.json" $record
Save "$project\.release\hermes\current.json" $record
$core.activeFrontend.version='0.3.22'
$core.hermesRelease.version='0.3.22'
$local=(docker inspect web-frontend-1 | ConvertFrom-Json)[0]
$core.localFrontend=@{version='0.3.22';target='web-frontend-1';url='http://192.168.10.107:3000/workflows';
    image=$record.images.frontend;containerId=$local.Id;startedAt=$local.State.StartedAt;verifiedAt=$record.verifiedAt;
    status='entry-verified';overrideHash=$record.candidateHash;backupDir=$record.backup;receipt="$project\.release\hermes\current.json"}
Save "$project\.release\current.json" $core
@{version=$record.version;status=$record.status;imported=106;reused=2;oldRowsUnchanged=$true;coreRuntimeImage=$runtimeCore;coreUnchanged=$true;generationRequests=0} | ConvertTo-Json
