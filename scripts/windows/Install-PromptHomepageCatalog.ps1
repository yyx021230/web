param(
    [Parameter(Mandatory = $true)]
    [string]$Archive,
    [Parameter(Mandatory = $true)]
    [string]$Sha256,
    [string]$Project = 'C:\projects\web',
    [string]$CatalogName = 'open-catalog-20260914'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Exec([scriptblock]$Action, [string]$Failure) {
    & $Action
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}

if (-not (Test-Path $Archive)) { throw "Prompt catalog archive is missing: $Archive" }
$actualSha256 = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha256 -ne $Sha256.ToLowerInvariant()) {
    throw "Prompt catalog checksum mismatch: expected $Sha256, got $actualSha256"
}

Set-Location $Project
$backendId = (docker compose ps -q backend).Trim()
if (-not $backendId) { throw 'Backend container is not running' }
$backend = (docker inspect $backendId | ConvertFrom-Json)[0]
$uploadsMount = @($backend.Mounts | Where-Object { $_.Destination -eq '/app/uploads' })
if ($uploadsMount.Count -ne 1) { throw 'Expected exactly one /app/uploads mount' }
$uploadsRoot = [string]$uploadsMount[0].Source
if (-not (Test-Path $uploadsRoot)) { throw "Uploads mount is missing: $uploadsRoot" }

Exec { tar -xzf $Archive -C $uploadsRoot } 'Prompt catalog extraction failed'
$manifest = "/app/uploads/prompts/catalog/$CatalogName/catalog.json"
$internalBefore = docker compose exec -T postgres psql -U postgres -d ai_creative -At -c `
    "SELECT count(*) FROM prompt_examples WHERE deleted_at IS NULL AND source_kind = 'internal';"
if ($LASTEXITCODE -ne 0) { throw 'Prompt catalog baseline verification failed' }
$internalBefore = [int]($internalBefore.Trim())

Exec {
    docker compose exec -T backend python -m app.scripts.replace_prompt_homepage_catalog `
        --manifest $manifest
} 'Prompt catalog database installation failed'

$counts = docker compose exec -T postgres psql -U postgres -d ai_creative -At -F '|' -c `
    "SELECT count(*) FILTER (WHERE source_kind = 'internal'), count(*) FILTER (WHERE source_kind = 'external'), count(*) FROM prompt_examples WHERE deleted_at IS NULL;"
if ($LASTEXITCODE -ne 0) { throw 'Prompt catalog count verification failed' }
$countParts = $counts.Trim().Split('|')
if ($countParts.Count -ne 3) { throw "Unexpected prompt catalog counts: $counts" }
$internalAfter = [int]$countParts[0]
$externalAfter = [int]$countParts[1]
$activeAfter = [int]$countParts[2]
if ($internalAfter -ne $internalBefore) {
    throw "Prompt catalog installation changed internal content: before=$internalBefore after=$internalAfter"
}
if ($externalAfter -ne 1000) {
    throw "Prompt catalog external verification failed: expected=1000 actual=$externalAfter"
}
if ($activeAfter -ne ($internalAfter + $externalAfter)) {
    throw "Prompt catalog total verification failed: internal=$internalAfter external=$externalAfter active=$activeAfter"
}
$sources = docker compose exec -T postgres psql -U postgres -d ai_creative -At -F '|' -c `
    "SELECT source_name, count(*) FROM prompt_examples WHERE deleted_at IS NULL AND source_kind = 'external' GROUP BY source_name ORDER BY source_name;"
if ($LASTEXITCODE -ne 0) { throw 'Prompt catalog source verification failed' }
$sourceRows = @($sources | Where-Object { $_ -and $_.Trim() })
if ($sourceRows.Count -ne 2 -or $sourceRows -notcontains 'DiffusionDB|100' -or $sourceRows -notcontains 'MeiGen Trending Prompts|900') {
    throw "Prompt catalog source distribution is invalid: $($sourceRows -join ', ')"
}

[pscustomobject]@{
    installed = $true
    mode = 'additive'
    internalBefore = $internalBefore
    internalAfter = $internalAfter
    external = $externalAfter
    active = $activeAfter
    archiveSha256 = $actualSha256
    uploadsRoot = $uploadsRoot
    sources = $sourceRows
} | ConvertTo-Json -Depth 5 -Compress
