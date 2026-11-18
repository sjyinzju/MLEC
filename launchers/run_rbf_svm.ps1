param(
    [string]$Python = 'python',
    [string]$DataRoot = '',
    [string]$OutputRoot = '',
    [int]$CpuWorkers = 0,
    [int]$CpuThreads = 1,
    [string]$RunId = ''
)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskRepo
try {
    $taskArgs = @('-m', 'scripts.market_state.experiments', 'pipeline', '--model', 'rbf_svm', '--config', 'config/experiments/rbf_svm.yaml', '--suite', 'full', '--execute', '--resume', '--cpu-workers', "$CpuWorkers", '--cpu-threads', "$CpuThreads")
    if ($DataRoot) { $taskArgs += @('--data-root', $DataRoot) }
    if ($OutputRoot) { $taskArgs += @('--output-root', $OutputRoot) }
    if ($RunId) { $taskArgs += @('--run-id', $RunId) }
    & $Python @taskArgs
    if ($LASTEXITCODE -ne 0) { throw "SVM pipeline stopped (exit $LASTEXITCODE). Keep the run directory and resume with the same research settings." }
} finally { Pop-Location }
