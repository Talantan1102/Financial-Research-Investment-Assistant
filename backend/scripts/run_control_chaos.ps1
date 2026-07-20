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

function Invoke-BoundedNative {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][int]$Timeout
    )
    $script:LastNativeResult = $null
    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    $process = $null
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden
        $completed = $process.WaitForExit([Math]::Max(1, $Timeout) * 1000)
        if (-not $completed) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $script:LastNativeResult = [pscustomobject]@{
                ExitCode = 124
                Stdout = (Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue)
                Stderr = ("command timeout after {0}s: {1}" -f $Timeout, (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue))
            }
            return
        }
        $script:LastNativeResult = [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = (Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue)
            Stderr = (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue)
        }
    } finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Get-RemainingSeconds {
    return [Math]::Max(1, [int][Math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds))
}

if ($Project -notmatch '^rcp-[a-z0-9][a-z0-9-]{2,62}$') {
    throw "Project must be an isolated rcp-* name"
}

try {
    Push-Location $repoRoot
    Invoke-BoundedNative -FilePath "docker" -Arguments @("compose", "-f", "docker-compose.yml", "config", "--quiet") -Timeout (Get-RemainingSeconds)
    if ($script:LastNativeResult.ExitCode -ne 0) { throw "Compose configuration failed: $($script:LastNativeResult.Stderr)" }
    Invoke-BoundedNative -FilePath ".venv\Scripts\python.exe" -Arguments @("-m", "pytest", "-q", "backend/tests/chaos/test_run_control_failures.py") -Timeout (Get-RemainingSeconds)
    if ($script:LastNativeResult.ExitCode -ne 0) { throw "Chaos self-tests failed: $($script:LastNativeResult.Stderr)" }
    Invoke-BoundedNative -FilePath ".venv\Scripts\python.exe" -Arguments @("-m", "tests.chaos.run_control_harness", "--repo-root", $repoRoot, "--project", $Project, "--evidence", $env:RUN_CONTROL_CHAOS_EVIDENCE, "--timeout", (Get-RemainingSeconds)) -Timeout (Get-RemainingSeconds)
    if ($script:LastNativeResult.ExitCode -ne 0) { throw "Compose chaos scenarios failed; evidence retained at $env:RUN_CONTROL_CHAOS_EVIDENCE" }
    if ([DateTime]::UtcNow -gt $deadline) { throw "Chaos suite exceeded bounded timeout" }
}
catch {
    $failure = [ordered]@{
        project = $Project
        failed_at_utc = [DateTime]::UtcNow.ToString("o")
        error = $_.Exception.Message
        exit_code = if ($script:LastNativeResult) { [int]$script:LastNativeResult.ExitCode } else { [int]$LASTEXITCODE }
        docker_stderr = if ($script:LastNativeResult) { [string]$script:LastNativeResult.Stderr } else { $_.Exception.Message }
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
        Invoke-BoundedNative -FilePath "docker" -Arguments @("compose", "-f", "docker-compose.yml", "-p", $Project, "--profile", "run-control", "down", "--volumes", "--remove-orphans") -Timeout $TimeoutSeconds
        if ($script:LastNativeResult.ExitCode -ne 0) { throw "Scoped Compose cleanup failed for ${Project}: $($script:LastNativeResult.Stderr)" }
        Invoke-BoundedNative -FilePath "docker" -Arguments @("ps", "-a", "--filter", "label=com.docker.compose.project=$Project", "--format", "{{.ID}}") -Timeout $TimeoutSeconds
        $leftovers = $script:LastNativeResult.Stdout
        if ($leftovers) { throw "Scoped cleanup left containers: $leftovers" }
        Invoke-BoundedNative -FilePath "docker" -Arguments @("network", "ls", "--filter", "label=com.docker.compose.project=$Project", "--format", "{{.ID}}") -Timeout $TimeoutSeconds
        $networks = $script:LastNativeResult.Stdout
        if ($networks) { throw "Scoped cleanup left networks: $networks" }
        Invoke-BoundedNative -FilePath "docker" -Arguments @("volume", "ls", "--filter", "label=com.docker.compose.project=$Project", "--format", "{{.Name}}") -Timeout $TimeoutSeconds
        $volumes = $script:LastNativeResult.Stdout
        if ($volumes) { throw "Scoped cleanup left volumes: $volumes" }
    } finally {
        Pop-Location
    }
}
