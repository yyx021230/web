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
Exec {
    docker compose exec -T backend python -m app.scripts.replace_prompt_homepage_catalog `
        --manifest $manifest --replace
} 'Prompt catalog database installation failed'

$active = docker compose exec -T postgres psql -U postgres -d ai_creative -At -c `
    "SELECT count(*) FROM prompt_examples WHERE deleted_at IS NULL;"
if ($LASTEXITCODE -ne 0 -or [int]($active.Trim()) -ne 1000) {
    throw "Prompt catalog verification failed: active=$active"
}
$sources = docker compose exec -T postgres psql -U postgres -d ai_creative -At -F '|' -c `
    "SELECT source_name, count(*) FROM prompt_examples WHERE deleted_at IS NULL GROUP BY source_name ORDER BY source_name;"
if ($LASTEXITCODE -ne 0) { throw 'Prompt catalog source verification failed' }

[pscustomobject]@{
    installed = $true
    active = 1000
    archiveSha256 = $actualSha256
    uploadsRoot = $uploadsRoot
    sources = @($sources)
} | ConvertTo-Json -Depth 5 -Compress
