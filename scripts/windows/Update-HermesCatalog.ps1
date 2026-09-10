param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$project = 'C:\projects\web'
$release = 'D:\ztqc-hermes-release\0.3.22'
$live = Join-Path $project 'docker-compose.override.yml'
$candidate = Join-Path $release 'compose.candidate.yml'
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Json($value) { return ConvertTo-Json -InputObject $value -Depth 100 -Compress }
function Write-Json([string]$path, $value) { [IO.File]::WriteAllText($path, (Json $value), $utf8) }
function Config([string]$path) {
    # Resolved secrets stay in memory, never printed or saved.
    $raw = docker compose --project-name web --project-directory $project -f "$project\docker-compose.yml" -f $path --profile hermes config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration failed' }
    return (($raw -join "`n") | ConvertFrom-Json)
}
function Snapshot([string]$name) {
    $c = (docker inspect $name | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Inspect failed: $name" }
    return @{name=$name; id=$c.Id; image=$c.Image; started=$c.State.StartedAt; running=$c.State.Running}
}
function Wait-Healthy([string]$name, [string]$image) {
    for ($i=0; $i -lt 60; $i++) {
        $c = (docker inspect $name | ConvertFrom-Json)[0]
        if ($LASTEXITCODE -eq 0 -and $c.Image -eq $image -and $c.State.Health.Status -eq 'healthy') { return }
        Start-Sleep -Seconds 2
    }
    throw "Health check failed: $name. Old images and Windows backup retained."
}
function Compose-Up([string]$services) {
    # cmd owns native stderr redirection to avoid PS5 treating progress as an error.
    cmd /c "docker compose --profile hermes up -d --no-deps --no-build $services >> $release\switch.log 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "Compose failed: $services; inspect switch.log" }
}
$beforeHash = (Get-FileHash $live).Hash
$raw = [IO.File]::ReadAllText($live)
$updated = $raw.Replace('ztqc/frontend:0.3.21','ztqc/frontend:0.3.22').Replace('ztqc/hermes-api:0.3.21','ztqc/hermes-api:0.3.22').Replace('ztqc/hermes-worker:0.3.21','ztqc/hermes-worker:0.3.22')
$updated = [regex]::Replace($updated, '(?m)(APP_VERSION:\s*")0\.3\.21(")', '${1}0.3.22$2')
$updated = [regex]::Replace($updated, '(?m)(NEXT_PUBLIC_GIT_COMMIT:\s*")[^"]*(")', '${1}catalog-183b4fda$2')
$updated = [regex]::Replace($updated, '(?m)(NEXT_PUBLIC_BUILD_TIME:\s*")[^"]*(")', '${1}2026-09-08T10:45:00Z$2')
[IO.File]::WriteAllText($candidate, $updated, $utf8)
$before = Config $live
$after = Config $candidate
$images = @{}
foreach ($service in @('frontend','hermes-frontend','hermes-api','hermes-worker')) {
    $base = if ($service -in @('frontend','hermes-frontend')) {'ztqc/frontend'} else {"ztqc/$service"}
    if ($before.services.$service.image -ne "${base}:0.3.21" -or $after.services.$service.image -ne "${base}:0.3.22") { throw "Unexpected service tag: $service" }
    $image = (docker image inspect "${base}:0.3.22" | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Missing candidate: $service" }
    if ($service -in @('frontend','hermes-frontend')) {
        if ($image.Config.Env -notcontains 'NEXT_PUBLIC_APP_VERSION=0.3.22' -or $image.Config.Env -notcontains 'NEXT_PUBLIC_GIT_COMMIT=catalog-183b4fda') { throw "Wrong frontend metadata: $service" }
    } elseif ($image.Config.Labels.'org.opencontainers.image.revision' -ne 'catalog-183b4fda') { throw "Wrong candidate revision: $service" }
    $images[$service] = $image.Id
    foreach ($config in @($before,$after)) {
        $config.services.$service.PSObject.Properties.Remove('image')
        foreach ($key in @('APP_VERSION','NEXT_PUBLIC_APP_VERSION','NEXT_PUBLIC_GIT_COMMIT','NEXT_PUBLIC_BUILD_TIME')) {
            $config.services.$service.environment.PSObject.Properties.Remove($key)
        }
    }
}
if ((Json $before) -cne (Json $after)) { throw 'Additional Compose changes outside images/version metadata' }
$untouched = @('web-backend-1','web-ai-worker-1','web-postgres-1','web-redis-1','web-minio-1')
$baseline = @($untouched | ForEach-Object { Snapshot $_ })
$frpIds = @(Get-Process frpc -ErrorAction Stop | Select-Object -ExpandProperty Id)
$frpHash = (Get-FileHash 'C:\ProgramData\frp\frpc.toml').Hash
$receipt = @{version='0.3.22'; revision='catalog-183b4fda'; images=$images; untouched=$baseline;
    beforeHash=$beforeHash;candidateHash=(Get-FileHash $candidate).Hash;frpUnchanged=$true;
    schemaMigration=$false;scheduleEnabledByRelease=$false;publisherEnabledByRelease=$false;generationRequests=0}
Write-Json "$release\preflight.json" $receipt
if (-not $Execute) { Write-Output (Json @{preflight='passed';images=$images;untouched=$untouched}); exit 0 }
if ((Get-FileHash $live).Hash -ne $beforeHash) { throw 'Configuration changed since preflight' }
$backup = Join-Path $release ('private\before_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $live "$backup\docker-compose.override.yml"
Copy-Item "$project\.release\current.json" "$backup\core-current.json"
Copy-Item "$project\.release\hermes\current.json" "$backup\hermes-current.json"
Copy-Item "$release\catalog-before.json" "$backup\catalog-before.json"
$receipt.backup = $backup
Write-Json "$release\deployment-started.json" $receipt
Write-Output 'Draining only Hermes Worker; website/API still accepts tasks.'
docker stop --timeout 2700 web-hermes-worker-1
if ($LASTEXITCODE -ne 0) { throw 'Worker did not drain; no replacements performed' }
if ((Get-FileHash $live).Hash -ne $beforeHash) { throw 'Live override changed during drain; stop for review' }
Copy-Item $candidate $live -Force
Set-Location $project
Compose-Up 'hermes-api'
Wait-Healthy 'web-hermes-api-1' $images['hermes-api']
Compose-Up 'hermes-worker'
Wait-Healthy 'web-hermes-worker-1' $images['hermes-worker']
Compose-Up 'frontend hermes-frontend'
Wait-Healthy 'web-frontend-1' $images['frontend']
Wait-Healthy 'web-hermes-frontend-1' $images['hermes-frontend']
foreach ($old in $baseline) {
    if ((Json (Snapshot $old.name)) -cne (Json $old)) { throw "Untargeted service changed: $($old.name)" }
}
if ((Json @(Get-Process frpc | Select-Object -ExpandProperty Id)) -ne (Json $frpIds) -or
    (Get-FileHash 'C:\ProgramData\frp\frpc.toml').Hash -ne $frpHash) { throw 'FRP unexpectedly changed' }
foreach ($url in @('http://127.0.0.1:3000/workflows/hermes/single','http://127.0.0.1:3101/workflows/hermes/single','http://47.98.127.132:18080/workflows/hermes/single')) {
    $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 20
    if ($r.StatusCode -ne 200) { throw "Page failed: $url" }
}
$receipt.status='deployed-awaiting-catalog-import'
$receipt.deployedAt=[DateTime]::UtcNow.ToString('o')
Write-Json "$release\release-receipt.json" $receipt
Write-Output (Json $receipt)
