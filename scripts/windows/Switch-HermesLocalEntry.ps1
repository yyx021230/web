param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$releaseDir = 'D:\ztqc-hermes-release\0.3.20'
$projectDir = 'C:\projects\web'
$live = Join-Path $projectDir 'docker-compose.override.yml'
$candidate = Join-Path $releaseDir 'compose.local3000.candidate.yml'
$expectedBefore = '76F9A0587F5EBFE2867F9DB9E764B54ED2806104247CA3EA381BB50FFD1D0575'
$expectedImage = 'sha256:a3aef33f3a21124c939771496f7b6acfe262b6c5df380b0d8606a13b605d81f1'
$marker = '/_next/static/chunks/7992-c75d50c27309179a.js'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-Compose([string]$overlay) {
    # Resolved configuration contains secrets: keep in memory, never print/save it.
    $raw = docker compose --project-name web --project-directory $projectDir -f (Join-Path $projectDir 'docker-compose.yml') -f $overlay --profile hermes config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed' }
    return (($raw -join "`n") | ConvertFrom-Json)
}
function Json($value) { return (ConvertTo-Json -InputObject $value -Depth 100 -Compress) }
function Inspect-Safe([string]$name) {
    $items = docker inspect $name | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Container inspect failed: $name" }
    $c = $items[0]
    return [pscustomobject]@{name=$name; id=$c.Id; image=$c.Image; startedAt=$c.State.StartedAt; restartCount=$c.RestartCount; running=$c.State.Running}
}
function Assert-Unchanged($baseline) {
    foreach ($before in $baseline) {
        $now = Inspect-Safe $before.name
        if ((Json $now) -cne (Json $before) -or -not $now.running) {
            throw "Untargeted container changed: $($before.name)"
        }
    }
}
function Check-Page([string]$url) {
    $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 10
    if ($r.StatusCode -ne 200 -or -not $r.Content.Contains($marker)) { throw "New frontend marker missing: $url" }
}
function Wait-Frontend {
    for ($i=0; $i -lt 40; $i++) {
        $c = (docker inspect web-frontend-1 | ConvertFrom-Json)[0]
        if ($LASTEXITCODE -eq 0 -and $c.State.Health.Status -eq 'healthy' -and $c.Image -eq $expectedImage) { return }
        Start-Sleep -Seconds 2
    }
    throw 'Original frontend did not become healthy on the verified image'
}

if ((Get-FileHash $live -Algorithm SHA256).Hash -ne $expectedBefore) { throw 'Live override differs from reviewed baseline; stop' }
$original = (docker inspect web-frontend-1 | ConvertFrom-Json)[0]
if ($LASTEXITCODE -ne 0 -or $original.Config.Image -ne 'ztqc/frontend:0.3.18' -or $original.State.Health.Status -ne 'healthy') { throw 'Original frontend is not the reviewed healthy 0.3.18 container' }
$newImage = (docker image inspect ztqc/frontend:0.3.20 | ConvertFrom-Json)[0]
if ($LASTEXITCODE -ne 0 -or $newImage.Id -ne $expectedImage) { throw 'Candidate frontend image differs from accepted build' }
Check-Page 'http://127.0.0.1:3101/workflows'
Check-Page 'http://47.98.127.132:18080/workflows'
$beforeConfig = Read-Compose $live
$afterConfig = Read-Compose $candidate
$f = $afterConfig.services.frontend
if ($f.image -ne 'ztqc/frontend:0.3.20' -or $f.PSObject.Properties['build'] -or
    $f.environment.HERMES_BACKEND_ORIGIN -ne 'http://hermes-api:8000' -or
    $f.environment.NEXT_PUBLIC_APP_VERSION -ne '0.3.20' -or
    $f.environment.NEXT_PUBLIC_GIT_COMMIT -ne '5bf479400f0891d8f762f5b081bfa2638069bf30' -or
    $f.environment.NEXT_PUBLIC_BUILD_TIME -ne '2026-09-08T06:14:00Z') { throw 'Candidate frontend override does not match the approved build' }
# Only image, removal of build, and these runtime metadata/routing fields may change.
foreach ($config in @($beforeConfig,$afterConfig)) {
    $config.services.frontend.PSObject.Properties.Remove('image')
    $config.services.frontend.PSObject.Properties.Remove('build')
    foreach ($key in @('HERMES_BACKEND_ORIGIN','NEXT_PUBLIC_APP_VERSION','NEXT_PUBLIC_GIT_COMMIT','NEXT_PUBLIC_BUILD_TIME')) {
        $config.services.frontend.environment.PSObject.Properties.Remove($key)
    }
}
if ((Json $beforeConfig) -cne (Json $afterConfig)) { throw 'Unexpected additional Compose changes; no deployment performed' }
$names = @('web-backend-1','web-ai-worker-1','web-postgres-1','web-redis-1','web-minio-1','web-hermes-api-1','web-hermes-worker-1','web-hermes-frontend-1')
$baseline = @($names | ForEach-Object { Inspect-Safe $_ })
Assert-Unchanged $baseline
$frpHash = (Get-FileHash 'C:\ProgramData\frp\frpc.toml' -Algorithm SHA256).Hash
$frpIds = @(Get-Process frpc -ErrorAction Stop | Select-Object -ExpandProperty Id)
$approvedHash = (Get-FileHash $candidate -Algorithm SHA256).Hash
if (-not $Execute) {
    [pscustomobject]@{preflight='passed'; changeTarget='web-frontend-1 only'; candidateHash=$approvedHash; image=$expectedImage; buildRemoved=$true; otherComposeFieldsUnchanged=$true; untouchedContainers=$names} | ConvertTo-Json -Depth 5
    exit 0
}

$backupDir = Join-Path $releaseDir ('private\local3000_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
Copy-Item $live (Join-Path $backupDir 'docker-compose.override.before.yml')
foreach ($item in @(@{source=(Join-Path $projectDir '.release\current.json'); name='core-current.before.json'},@{source=(Join-Path $projectDir '.release\hermes\current.json'); name='hermes-current.before.json'},@{source=(Join-Path $releaseDir 'release-receipt.json'); name='release-receipt.before.json'})) {
    Copy-Item $item.source (Join-Path $backupDir $item.name)
}
[IO.File]::WriteAllText((Join-Path $releaseDir 'local3000-baseline.json'), (Json $baseline), $utf8)
$started = [DateTime]::UtcNow.ToString('o')
try {
    if ((Get-FileHash $live -Algorithm SHA256).Hash -ne $expectedBefore -or (Get-FileHash $candidate -Algorithm SHA256).Hash -ne $approvedHash) { throw 'Configuration changed since preflight' }
    Copy-Item $candidate $live -Force
    Push-Location $projectDir
    try { docker compose --project-name web --profile hermes up -d --no-deps --no-build frontend; if ($LASTEXITCODE -ne 0) { throw 'Frontend recreate failed' } }
    finally { Pop-Location }
    Wait-Frontend
    Check-Page 'http://127.0.0.1:3000/workflows'
    Check-Page 'http://127.0.0.1:3101/workflows'
    Check-Page 'http://47.98.127.132:18080/workflows'
    $probe = docker exec web-hermes-worker-1 python /tmp/probe_hermes_release.py --api-root http://frontend:3000/api/backend
    if ($LASTEXITCODE -ne 0) { throw 'Original-entry authenticated acceptance failed' }
    [IO.File]::WriteAllText((Join-Path $releaseDir 'local3000-acceptance.json'), ($probe -join "`n"), $utf8)
    $images = docker exec web-hermes-worker-1 python /tmp/accept_hermes_release.py --verify-images --api-root http://frontend:3000/api/backend
    if ($LASTEXITCODE -ne 0) { throw 'Original-entry image/data acceptance failed' }
    [IO.File]::WriteAllText((Join-Path $releaseDir 'local3000-image-acceptance.json'), ($images -join "`n"), $utf8)
    Assert-Unchanged $baseline
    if ((Get-FileHash 'C:\ProgramData\frp\frpc.toml' -Algorithm SHA256).Hash -ne $frpHash -or (Json @(Get-Process frpc | Select-Object -ExpandProperty Id)) -ne (Json $frpIds)) { throw 'FRP changed unexpectedly' }
}
catch {
    Copy-Item (Join-Path $backupDir 'docker-compose.override.before.yml') $live -Force
    Push-Location $projectDir
    try { docker compose --project-name web --profile hermes up -d --no-deps --no-build frontend; $rollbackExit = $LASTEXITCODE }
    finally { Pop-Location }
    [IO.File]::WriteAllText((Join-Path $releaseDir 'local3000-failure.txt'), "Failure at $([DateTime]::UtcNow.ToString('o')); restored override; rollback exit=$rollbackExit", $utf8)
    throw
}
$receipt = [ordered]@{
    status='verified'; startedAt=$started; verifiedAt=[DateTime]::UtcNow.ToString('o')
    target='web-frontend-1'; url='http://192.168.10.107:3000/workflows'
    version='0.3.20'; image=$expectedImage; overrideHash=$approvedHash; backupDir=$backupDir
    publicEntryUnchanged=$true; untouchedContainers=$names
    recreatedFrontend=(Inspect-Safe 'web-frontend-1'); newGenerationRequests=0
    acceptance='local3000-acceptance.json'; imageAcceptance='local3000-image-acceptance.json'
}
[IO.File]::WriteAllText((Join-Path $releaseDir 'local3000-cutover.json'), (ConvertTo-Json $receipt -Depth 10), $utf8)
# Core backend version remains 0.3.18; record the additional frontend entry separately.
foreach ($path in @((Join-Path $projectDir '.release\current.json'),(Join-Path $projectDir '.release\hermes\current.json'),(Join-Path $releaseDir 'release-receipt.json'))) {
    $metadata = [IO.File]::ReadAllText($path) | ConvertFrom-Json
    $metadata | Add-Member -NotePropertyName localFrontend -NotePropertyValue $receipt -Force
    [IO.File]::WriteAllText($path, (ConvertTo-Json $metadata -Depth 30), $utf8)
}
Copy-Item $candidate (Join-Path $releaseDir 'compose.hermes-release.yml') -Force
$receipt | ConvertTo-Json -Depth 10
