param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$releaseDir = 'D:\ztqc-hermes-release\0.3.20'
$configPath = 'C:\ProgramData\frp\frpc.toml'
$backupPath = Join-Path $releaseDir 'private\frpc.before.toml'
$taskName = 'FRP-Windows-Web-Tunnel'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Assert-LegacyUnchanged {
    $baseline = Get-Content (Join-Path $releaseDir 'baseline-containers.json') -Raw | ConvertFrom-Json
    foreach ($before in $baseline) {
        $now = (docker inspect $before.name | ConvertFrom-Json)[0]
        if ($LASTEXITCODE -ne 0 -or $now.Id -ne $before.id -or
            $now.State.StartedAt -ne $before.startedAt -or $now.Image -ne $before.image -or
            $now.RestartCount -ne $before.restartCount -or -not $now.State.Running) {
            throw "Original container changed: $($before.name)"
        }
    }
}

function Restart-EntryOnly {
    $entry = @(Get-CimInstance Win32_Process -Filter "Name='frpc.exe'" | Where-Object {
        $_.ExecutablePath -eq 'C:\ProgramData\frp\frpc.exe' -and
        $_.CommandLine.Contains('C:\ProgramData\frp\frpc.toml')
    })
    if ($entry.Count -gt 1) { throw 'Ambiguous FRP process target' }
    Stop-ScheduledTask -TaskName $taskName
    Start-Sleep -Milliseconds 700
    # Task Scheduler may leave the child process alive; resolve its exact identity again.
    foreach ($before in $entry) {
        $remaining = Get-CimInstance Win32_Process -Filter "ProcessId=$($before.ProcessId)"
        if ($remaining -and $remaining.ExecutablePath -eq $before.ExecutablePath -and
            $remaining.CommandLine -eq $before.CommandLine) {
            Stop-Process -Id $before.ProcessId
        }
    }
    Start-ScheduledTask -TaskName $taskName
}

Assert-LegacyUnchanged
foreach ($name in @('web-hermes-api-1','web-hermes-frontend-1','web-hermes-worker-1')) {
    $state = (docker inspect $name | ConvertFrom-Json)[0].State
    if ($LASTEXITCODE -ne 0 -or $state.Health.Status -ne 'healthy') { throw "Candidate unhealthy: $name" }
}
$newPage = Invoke-WebRequest 'http://127.0.0.1:3101/workflows' -UseBasicParsing -TimeoutSec 10
$oldPage = Invoke-WebRequest 'http://127.0.0.1:3000/workflows' -UseBasicParsing -TimeoutSec 10
$releaseMarker = @([regex]::Matches($newPage.Content, 'src="(/_next/static/[^" ]+\.js)"') |
    ForEach-Object { $_.Groups[1].Value } | Where-Object { -not $oldPage.Content.Contains($_) }) | Select-Object -First 1
if (-not $releaseMarker) { throw 'Cannot distinguish candidate frontend assets from legacy assets' }
$acceptanceRaw = docker exec web-hermes-worker-1 python /tmp/accept_hermes_release.py
if ($LASTEXITCODE -ne 0) { throw 'Acceptance read failed' }
$acceptance = ($acceptanceRaw -join "`n") | ConvertFrom-Json
if ($acceptance.id -ne 1 -or $acceptance.generated_posts -ne 1 -or $acceptance.failed_posts -ne 0 -or
    $acceptance.schedule_enabled -ne $false -or $acceptance.posts[0].hard_pass -ne $true -or
    $acceptance.posts[0].status -ne 'review_pending' -or
    $acceptance.posts[0].publish_status -ne 'not_requested') { throw 'Real acceptance post is not ready' }
if ($acceptance.posts[0].image_url -notmatch '^/uploads/ai-images/') {
    throw 'Acceptance image must be served through the existing browser-accessible uploads route'
}
$original = [IO.File]::ReadAllText($configPath)
if ($original -ne [IO.File]::ReadAllText($backupPath)) { throw 'FRP changed since reviewed backup' }
if ([regex]::Matches($original, '(?m)^\s*\[\[proxies\]\]\s*$').Count -ne 1 -or
    $original -notmatch 'name\s*=\s*"windows-web"' -or
    [regex]::Matches($original, '(?m)^localPort\s*=\s*3000\s*$').Count -ne 1) { throw 'Unexpected FRP target' }
$candidate = [regex]::Replace($original, '(?m)^localPort\s*=\s*3000(?=\s*$)', 'localPort = 3101')
$candidatePath = Join-Path $releaseDir 'private\frpc.candidate.toml'
[IO.File]::WriteAllText($candidatePath, $candidate, $utf8)
& 'C:\ProgramData\frp\frpc.exe' verify -c $candidatePath
if ($LASTEXITCODE -ne 0) { throw 'Candidate FRP syntax invalid' }
if (-not $Execute) { Write-Output 'Preflight passed; no public-entry change'; exit 0 }

$started = [DateTime]::UtcNow.ToString('o')
try {
    [IO.File]::WriteAllText($configPath, $candidate, $utf8)
    Restart-EntryOnly
    $reachable = $false
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
        try {
            $page = Invoke-WebRequest 'http://47.98.127.132:18080/workflows' -UseBasicParsing -TimeoutSec 4
            if ($page.StatusCode -eq 200 -and $page.Content.Contains($releaseMarker)) { $reachable = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 1200
    }
    if (-not $reachable) { throw 'New public webpage did not become ready' }
    $publicProbe = docker exec web-hermes-worker-1 python /tmp/probe_hermes_release.py --api-root http://47.98.127.132:18080/api/backend
    if ($LASTEXITCODE -ne 0) { throw 'Public authenticated route acceptance failed' }
    [IO.File]::WriteAllText((Join-Path $releaseDir 'public-acceptance.json'), ($publicProbe -join "`n"), $utf8)
    Assert-LegacyUnchanged
    $receipt = @{ status='switched'; startedAt=$started; verifiedAt=[DateTime]::UtcNow.ToString('o');
        oldPort=3000; newPort=3101; publicUrl='http://47.98.127.132:18080/workflows';
        originalContainersUnchanged=$true; acceptanceRunId=1; scheduleEnabled=$false; publishingEnabled=$false;
        releaseAsset=$releaseMarker }
    [IO.File]::WriteAllText((Join-Path $releaseDir 'entry-cutover.json'), ($receipt | ConvertTo-Json), $utf8)
    $receipt | ConvertTo-Json
} catch {
    [IO.File]::WriteAllText($configPath, $original, $utf8)
    Restart-EntryOnly
    [IO.File]::WriteAllText((Join-Path $releaseDir 'entry-cutover-failed.txt'),
        "Restored original entry config after failure at $([DateTime]::UtcNow.ToString('o'))", $utf8)
    throw
}
