[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 900,
    [string]$Project = "rcp-chaos-$([guid]::NewGuid().ToString('N').Substring(0,8))",
    [string]$EvidencePath = "artifacts/run-control-chaos.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$startedAt = [DateTime]::UtcNow
$evidenceAbsolute = [IO.Path]::GetFullPath((Join-Path $repoRoot $EvidencePath))
$evidenceParent = Split-Path -Parent $evidenceAbsolute
New-Item -ItemType Directory -Path $evidenceParent -Force | Out-Null
$env:RUN_CONTROL_COMPOSE_PROJECT = $Project
$env:RUN_CONTROL_CHAOS_EVIDENCE = $evidenceAbsolute
$env:RUN_CONTROL_CHAOS_TIMEOUT_SECONDS = [string]$TimeoutSeconds
$env:RUN_CONTROL_COMMAND_TIMEOUT = [string]([Math]::Max(1, [Math]::Min($TimeoutSeconds, 60)))
$env:PYTHONPATH = (Join-Path $repoRoot "backend")
$env:RUN_CONTROL_COMPOSE_SELF_BOOTSTRAP = "1"
$env:RUN_CONTROL_COMPOSE_CLEANUP_FAILURE_INJECTION = "0"

if ($Project -notmatch '^rcp-[a-z0-9][a-z0-9-]{2,62}$') {
    throw "Project must be an isolated rcp-* name"
}

try {
    Push-Location $repoRoot
    & docker compose -f docker-compose.yml config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Compose configuration failed" }
    & .venv\Scripts\python.exe -m pytest -q backend/tests/chaos/test_run_control_failures.py
    if ($LASTEXITCODE -ne 0) { throw "Chaos self-tests failed" }
    & .venv\Scripts\python.exe -m tests.chaos.run_control_harness --repo-root $repoRoot --project $Project --evidence $env:RUN_CONTROL_CHAOS_EVIDENCE --timeout $TimeoutSeconds
    if ($LASTEXITCODE -ne 0) { throw "Compose chaos scenarios failed; evidence retained at $env:RUN_CONTROL_CHAOS_EVIDENCE" }
    if ([DateTime]::UtcNow -gt $deadline) { throw "Chaos suite exceeded bounded timeout" }
}
catch {
    $failure = [ordered]@{
        project = $Project
        failed_at_utc = [DateTime]::UtcNow.ToString("o")
        error = $_.Exception.Message
        docker_stderr = $_.Exception.Message
        exit_code = [int]$LASTEXITCODE
        elapsed_seconds = ([DateTime]::UtcNow - $startedAt).TotalSeconds
    } | ConvertTo-Json
    $evidence = @()
    if (Test-Path -LiteralPath $env:RUN_CONTROL_CHAOS_EVIDENCE) {
        try {
            $parsed = Get-Content -LiteralPath $env:RUN_CONTROL_CHAOS_EVIDENCE -Raw -Encoding utf8 | ConvertFrom-Json
            if ($parsed -is [System.Array]) { $evidence = @($parsed) } elseif ($parsed) { $evidence = @($parsed) }
        } catch { $evidence = @() }
    }
    $evidence += [pscustomobject]($failure | ConvertFrom-Json)
    try {
        $json = $evidence | ConvertTo-Json -Depth 8
        [IO.File]::WriteAllText($env:RUN_CONTROL_CHAOS_EVIDENCE, $json, [Text.UTF8Encoding]::new($false))
    } catch {
        # Never replace the original CLI/Docker failure with an evidence-write error.
        Write-Error ("Unable to persist chaos evidence: " + $_.Exception.Message)
    }
    throw
}
finally {
    try {
        & docker compose -f docker-compose.yml -p $Project --profile run-control down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw "Scoped Compose cleanup failed for $Project" }
        $leftovers = & docker ps -a --filter "label=com.docker.compose.project=$Project" --format "{{.ID}}"
        if ($leftovers) { throw "Scoped cleanup left containers: $leftovers" }
        $networks = & docker network ls --filter "label=com.docker.compose.project=$Project" --format "{{.ID}}"
        if ($networks) { throw "Scoped cleanup left networks: $networks" }
        $volumes = & docker volume ls --filter "label=com.docker.compose.project=$Project" --format "{{.Name}}"
        if ($volumes) { throw "Scoped cleanup left volumes: $volumes" }
    } finally {
        Pop-Location
    }
}
