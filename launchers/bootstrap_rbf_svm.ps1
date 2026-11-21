param(
    [switch]$PlanOnly,
    [ValidateSet('START','CHECK','TECHNICAL')][string]$Action = 'START',
    [string]$Python = '',
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
    $taskCheck = "import sys,struct; assert sys.version_info[:2]==(3,11) and struct.calcsize('P')==8, '64-bit Python 3.11 required'"
    if (-not $Python) {
        if ($env:MLEC_PYTHON) { $Python = $env:MLEC_PYTHON }
    }
    if (-not $Python) {
        $Python = Join-Path $taskRepo '.venv-rbf-svm\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $Python)) {
            $taskPy = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($taskPy) { $taskBase = $taskPy.Source; $taskPrefix = @('-3.11') }
            else {
                $taskPy = Get-Command python.exe -ErrorAction SilentlyContinue
                if (-not $taskPy) { throw 'Install 64-bit Python 3.11 with PATH enabled, or pass -Python C:\env\Scripts\python.exe.' }
                $taskBase = $taskPy.Source; $taskPrefix = @()
            }
            & $taskBase @taskPrefix -c $taskCheck
            if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 (64-bit) was not found. Install it and reopen this launcher.' }
            & $taskBase @taskPrefix -m venv (Join-Path $taskRepo '.venv-rbf-svm')
            if ($LASTEXITCODE -ne 0) { throw 'Cannot create venv. Extract the package to a writable directory and install Python venv support.' }
        }
    }
    & $Python -c $taskCheck
    if ($LASTEXITCODE -ne 0) { throw 'The selected environment must use 64-bit Python 3.11.' }
    $taskDependencies = @'
import sys
try:
    from scripts.market_state.experiments.runtime import environment
    environment()
except Exception:
    sys.exit(1)
'@
    & $Python -c $taskDependencies
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing pinned dependencies. Internet access to PyPI (or a configured mirror) is required on first use.'
        if (Test-Path -Path 'wheels\*.whl') {
            & $Python -m pip install --no-index --find-links wheels --disable-pip-version-check -r requirements-experiments.txt
        } else {
            & $Python -m pip install --disable-pip-version-check -r requirements-experiments.txt
        }
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet/proxy or install the pinned requirements in the selected environment, then restart.' }
    }
    & $Python -c 'from scripts.market_state.experiments.runtime import environment; environment()'
    if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency verification failed. Read the package/version error above.' }
    if (Test-Path -LiteralPath 'package.manifest.json') {
        & $Python -m scripts.market_state.experiments.portable --verify .
        if ($LASTEXITCODE -ne 0) { throw 'Package integrity check failed.' }
    }
    if ($Action -eq 'CHECK') {
        $taskArgs = @('-m','scripts.market_state.experiments','preflight','--model','rbf_svm','--config','config/experiments/rbf_svm.yaml','--suite','full','--cpu-workers',"$CpuWorkers")
        if ($DataRoot) { $taskArgs += @('--data-root',$DataRoot) }
        if ($OutputRoot) { $taskArgs += @('--output-root',$OutputRoot) }
        & $Python @taskArgs
        if ($LASTEXITCODE -ne 0) { throw 'Non-training preflight failed.' }
    } elseif ($Action -eq 'TECHNICAL') {
        $taskArgs = @('-m','scripts.market_state.experiments.technical','--model','rbf_svm','--quick','--execute','--cpu-workers',"$CpuWorkers")
        if ($DataRoot) { $taskArgs += @('--data-root',$DataRoot) }
        & $Python @taskArgs
        if ($LASTEXITCODE -ne 0) { throw 'Technical verification stopped. No formal B/C was started.' }
    } else {
        & (Join-Path $PSScriptRoot 'run_rbf_svm.ps1') -PlanOnly:$PlanOnly -Python $Python -DataRoot $DataRoot -OutputRoot $OutputRoot -CpuWorkers $CpuWorkers -CpuThreads $CpuThreads -RunId $RunId
    }
} finally { Pop-Location }
