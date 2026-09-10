$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$project='C:\projects\web'
$release='D:\ztqc-hermes-release\0.3.23'
$utf8=New-Object Text.UTF8Encoding($false)
function ReadJson($path){return Get-Content $path -Raw -Encoding UTF8|ConvertFrom-Json}
function Save($path,$value){[IO.File]::WriteAllText($path,($value|ConvertTo-Json -Depth 100),$utf8)}
$record=ReadJson "$release\release-receipt.json"
$after=ReadJson "$release\policy-after.json"
$worker=ReadJson "$release\policy-worker.json"
$installed=ReadJson "$release\policy-installed.json"
$prepared=ReadJson "$release\policy\prepared.json"
$previous=ReadJson "$($record.serviceBackup)\hermes-current.json"
if($record.version -ne '0.3.23' -or (Get-FileHash "$project\docker-compose.override.yml").Hash -ne $record.candidateHash){throw 'Unexpected live release'}
if(-not $after.old_rows_unchanged -or -not $worker.live_refresh_verified -or -not $worker.production_config_and_cache_unchanged -or -not $installed.other_config_files_unchanged){throw 'Missing acceptance evidence'}
if($after.policy_sha256 -ne $prepared.files.'cases.json' -or $worker.configuration_count -ne 58){throw 'Policy mismatch'}
$c=(docker inspect web-hermes-worker-1|ConvertFrom-Json)[0]
if($c.Image -ne $record.workerImage -or $c.State.Health.Status -ne 'healthy'){throw 'Wrong Worker image or health'}
foreach($old in $record.untouched){
    $live=(docker inspect $old.name|ConvertFrom-Json)[0]
    if($live.Id -ne $old.id -or $live.Image -ne $old.image -or $live.State.StartedAt -ne $old.started){throw "Other service changed: $($old.name)"}
}
$images=$previous.images
$images.'hermes-worker'=$record.workerImage
$issues=@($previous.carriedForwardContentIssues)+@{
    kind='pre-existing-spaced-model-alias';model='Lafa5 Ultra';status='reported-to-user-not-changed-in-policy-release';
    evidence='Reproduced on 0.3.22: spaced Lafa5 Ultra incorrectly fails target/other-model checks; compact Lafa5Ultra passes.';
    productionRulesChanged=$false
}
foreach($entry in @{
    status='live-policy-verified';verifiedAt=[DateTime]::UtcNow.ToString('o');revision='policy-20260909-b9b93a75';images=$images;
    serviceVersions=@{worker='0.3.23';api='0.3.22';frontend='0.3.22'};
    sourceUrl=$prepared.share_url;sourceSha256=$prepared.source_sha256;policySha256=$after.policy_sha256;
    acceptance=@{cases=11;configurations=58;oldRowsUnchanged=$true;otherConfigUnchanged=$true;workerRefresh=$worker;
        publicBrowser='Verified latest-policy panel: September title, new source link, hidden local amounts, A05 23824 and report landing estimates';
        windowsEntry='Reachable; same API and shared policy volume; browser login was not changed';
        generationRequests=0;scope='Policy parsing, prompts and static guards only; no generated content acceptance'};
    regressionTests=@{production=390;apiPolicyWorkflows=38;total=428};
    carriedForwardContentIssues=$issues;previousCatalogRelease=@{version='0.3.22';receipt='D:\ztqc-hermes-release\0.3.22\release-receipt.json'};
    registrySha256=$previous.registrySha256;coreChangedByRelease=$false;schemaMigration=$false;
    scheduleEnabledByRelease=$false;publisherEnabledByRelease=$false;frpUnchanged=$true;backupsCopiedToMac=$false;
    rollback=@{workerImage='ztqc/hermes-worker:0.3.22';composeBackup="$($record.serviceBackup)\docker-compose.override.yml";
        policyBackup="$release\$($installed.backup_relative_path)";requiresWorkerDrain=$true;databaseRestore=$false;
        note='Inspect current tasks and policy first. Drain Worker, restore only three policy JSON files and two cache files, revert only Worker image. Never restore the database or alter history.'};
    limits=@('Source report estimates are not independently verified transaction/tax/insurance amounts',
        'No new image generation was authorized or performed; static checks are not a guarantee of every future output',
        'Existing model-alias and prior non-equivalent image-slot issues are not fixed by this policy release')
}.GetEnumerator()){$record|Add-Member -NotePropertyName $entry.Key -NotePropertyValue $entry.Value -Force}
Save "$release\release-receipt.json" $record
Save "$project\.release\hermes\current.json" $record
# Update the module pointer only; frontend/core version metadata stays unchanged.
$core=ReadJson "$project\.release\current.json"
$core.hermesRelease.version='0.3.23'
Save "$project\.release\current.json" $core
@{status=$record.status;workerVersion='0.3.23';frontendVersion='0.3.22';caseCount=11;configurationCount=58;generationRequests=0;oldRowsUnchanged=$true}|ConvertTo-Json
