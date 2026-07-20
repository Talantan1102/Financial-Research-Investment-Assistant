[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 900,
    [string]$Project = "rcp-chaos-$([guid]::NewGuid().ToString('N').Substring(0,8))",
    [string]$EvidencePath = "artifacts/run-control-chaos.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$env:RUN_CONTROL_COMPOSE_PROJECT = $Project
$env:RUN_CONTROL_CHAOS_EVIDENCE = (Join-Path $repoRoot $EvidencePath)
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
    & .venv\Scripts\python.exe -m pytest -q backend/tests/integration/test_run_control_multi_process.py -k 'compose_l25'
    if ($LASTEXITCODE -ne 0) { throw "Compose acceptance failed" }
    if ([DateTime]::UtcNow -gt $deadline) { throw "Chaos suite exceeded bounded timeout" }
}
finally {
    Pop-Location
}
