param(
    [ValidateRange(1, 20)]
    [int]$Rounds = 5,
    [switch]$Forever,
    [ValidateRange(60, 86400)]
    [int]$IntervalSeconds = 3600
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not $env:CURSOR_API_KEY) {
    Write-Error "CURSOR_API_KEY is not configured; agent mode cannot start."
}

$Arguments = @(
    "-3.13",
    "-m",
    "arena.orchestrator",
    "--rounds",
    $Rounds,
    "--require-agents"
)
if ($Forever) {
    $Arguments += @("--forever", "--interval-seconds", $IntervalSeconds)
}

& py @Arguments
exit $LASTEXITCODE
