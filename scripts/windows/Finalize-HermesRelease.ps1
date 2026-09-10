$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$releaseDir = 'D:\ztqc-hermes-release\0.3.20'
$entry = Get-Content "$releaseDir\entry-cutover.json" -Raw | ConvertFrom-Json
$accept = Get-Content "$releaseDir\public-image-url-acceptance.json" -Raw | ConvertFrom-Json
if ($entry.status -ne 'switched' -or -not $accept.content_provenance_version_unchanged) {
    throw 'Acceptance receipts incomplete'
}
$components = @()
foreach ($name in @('web-hermes-frontend-1','web-hermes-api-1','web-hermes-worker-1','web-backend-1','web-ai-worker-1')) {
    $item = (docker inspect $name | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $name" }
    $components += [pscustomobject]@{name=$name;image=$item.Config.Image;imageId=$item.Image;
        containerId=$item.Id;startedAt=$item.State.StartedAt;health=$item.State.Health.Status}
}
$head = docker exec web-postgres-1 psql -U postgres -d ai_creative -At -c 'SELECT version_num FROM alembic_version;'
if ($LASTEXITCODE -ne 0 -or $head.Trim() -ne 'c3d4e5f6a7b8') { throw 'Unexpected database head' }
$record = [ordered]@{
    version='0.3.20';deploymentMode='parallel-hermes-module';status='live';
    deployedAt=$entry.verifiedAt;verifiedAt=[DateTime]::UtcNow.ToString('o');
    publicUrl=$entry.publicUrl;frontendCommit='5bf479400f0891d8f762f5b081bfa2638069bf30';
    apiCommit='cecb6dfeb9a377ac6dc6270544b517092b307677';components=$components;
    databaseHead=$head.Trim();databaseBackup='D:\ztqc-backups\web\20260908_143009';
    fullImagesBackupSkippedWithApproval=$true;backupsCopiedToMac=$false;
    originalContainersUnchanged=$true;scheduleEnabled=$false;publishingEnabled=$false;
    backendTests=@{passed=732;seconds=113.20};frontendTests=@{passed=57};
    acceptance=@{runId=1;postId=1;imageTaskId=30403;generationSeconds=288.49;submittedImages=1;
        status='review_pending';browserImagesVerified=$true;contentUnchanged=$true};
    rollback=@{frontendPort=3000;frpBackup='D:\ztqc-hermes-release\0.3.20\private\frpc.before.toml';restoreDatabase=$false};
    limits=@('One real acceptance post; not a 40-post throughput or long-term stability guarantee',
        'Created time display has pre-existing UTC/CST offset; unchanged')
}
$json = $record | ConvertTo-Json -Depth 8
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText("$releaseDir\release-receipt.json", $json, $utf8)
[IO.File]::WriteAllText('C:\projects\web\.release\hermes\current.json', $json, $utf8)
$legacy = Get-Content 'C:\projects\web\.release\current.json' -Raw | ConvertFrom-Json
if ($legacy.version -ne '0.3.18' -or $legacy.PSObject.Properties.Name -contains 'hermesRelease') {
    throw 'Unexpected legacy release metadata; module receipt saved separately'
}
# Keep the untouched core release version accurate; record the module separately.
$legacy | Add-Member -NotePropertyName activeFrontend -NotePropertyValue @{version='0.3.20';service='hermes-frontend';port=3101}
$legacy | Add-Member -NotePropertyName hermesRelease -NotePropertyValue @{version='0.3.20';receipt='C:\projects\web\.release\hermes\current.json'}
[IO.File]::WriteAllText('C:\projects\web\.release\current.json', ($legacy | ConvertTo-Json -Depth 6), $utf8)
$json
