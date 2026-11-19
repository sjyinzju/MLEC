param(
    [string]$Python = 'python',
    [string]$DataRoot = '',
    [string]$OutputRoot = '',
    [int]$CpuThreads = 1,
    [int]$CpuWorkers = 0,
    [string]$RunId = ''
)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskRepo
try {
    $taskArgs = @('-m', 'scripts.market_state.experiments', 'pipeline', '--model', 'elastic_net', '--config', 'config/experiments/elastic_net.yaml', '--suite', 'full', '--execute', '--resume', '--cpu-threads', "$CpuThreads", '--cpu-workers', "$CpuWorkers")
    if ($DataRoot) { $taskArgs += @('--data-root', $DataRoot) }
    if ($OutputRoot) { $taskArgs += @('--output-root', $OutputRoot) }
    if ($RunId) { $taskArgs += @('--run-id', $RunId) }
    & $Python @taskArgs
    if ($LASTEXITCODE -ne 0) { throw "Elastic Net pipeline failed (exit $LASTEXITCODE). Resume with the same settings." }
} finally { Pop-Location }
