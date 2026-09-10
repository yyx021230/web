param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$project = 'C:\projects\web'
$release = 'D:\ztqc-hermes-release\0.3.21'
$live = Join-Path $project 'docker-compose.override.yml'
$candidate = Join-Path $release 'compose.candidate.yml'
$expectedBefore = 'FA5F985D20FAA4090F0A0EDB2953122CE7BE7FC2B3C0F18115F0C81B95A70B93'
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Json($value) { return ConvertTo-Json -InputObject $value -Depth 100 -Compress }
function Write-Json([string]$path, $value) { [IO.File]::WriteAllText($path, (Json $value), $utf8) }
function Config([string]$path) {
    # Secrets remain in memory. Do not print/save resolved Compose configuration.
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
    throw "Health check failed: $name. Retained old images and backup; inspect before rollback."
}
if ((Get-FileHash $live -Algorithm SHA256).Hash -ne $expectedBefore) { throw 'Live override changed; stop for review' }
$before = Config $live
$after = Config $candidate
$images = @{}
foreach ($service in @('frontend','hermes-frontend','hermes-api','hermes-worker')) {
    $tag = if ($service -in @('frontend','hermes-frontend')) {'ztqc/frontend:0.3.21'} else {"ztqc/${service}:0.3.21"}
    if ($after.services.$service.image -ne $tag) { throw "Wrong candidate tag: $service" }
    $image = (docker image inspect $tag | ConvertFrom-Json)[0]
    if ($LASTEXITCODE -ne 0) { throw "Missing candidate image: $tag" }
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
$receipt = @{version='0.3.21'; codeCommit='c1d38bac9b743b53f356c95776c706bb71c08364'; images=$images;
             untouched=$baseline; candidateHash=(Get-FileHash $candidate).Hash; frpUnchanged=$true;
             schemaMigration=$false; scheduleEnabled=$false; publisherEnabled=$false}
Write-Json "$release\preflight.json" $receipt
if (-not $Execute) { Write-Output (Json @{preflight='passed';images=$images;untouched=$untouched}); exit 0 }
$backup = Join-Path $release ('private\before_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $live "$backup\docker-compose.override.yml"
Copy-Item "$project\.release\current.json" "$backup\core-current.json"
Copy-Item "$project\.release\hermes\current.json" "$backup\hermes-current.json"
$receipt.backup = $backup
Write-Json "$release\deployment-started.json" $receipt
Write-Output 'Draining only the Hermes worker; the Web API keeps accepting new tasks.'
# SIGTERM is handled by the worker: finish current run before exit, no queue deletion.
docker stop --timeout 2700 web-hermes-worker-1
if ($LASTEXITCODE -ne 0) { throw 'Worker did not drain; no API/frontend replacement performed' }
Copy-Item $candidate $live -Force
Set-Location $project
docker compose --profile hermes up -d --no-deps --no-build hermes-api
if ($LASTEXITCODE -ne 0) { throw 'API deployment failed' }
Wait-Healthy 'web-hermes-api-1' $images['hermes-api']
docker compose --profile hermes up -d --no-deps --no-build hermes-worker
if ($LASTEXITCODE -ne 0) { throw 'Worker deployment failed' }
Wait-Healthy 'web-hermes-worker-1' $images['hermes-worker']
docker compose --profile hermes up -d --no-deps --no-build frontend hermes-frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend deployment failed' }
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
$receipt.status = 'deployed-awaiting-content-acceptance'
$receipt.deployedAt = [DateTime]::UtcNow.ToString('o')
Write-Json "$release\release-receipt.json" $receipt
Write-Output (Json $receipt)
