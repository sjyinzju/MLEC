@echo off
setlocal
cd /d "%~dp0"
if /I "%MLEC_ACTION%"=="CHECK" (echo MLEC Elastic Net: CHECK ONLY, no supervised fitting.) else if /I "%MLEC_ACTION%"=="TECHNICAL" (echo MLEC Elastic Net: short real technical verification only.) else (echo MLEC Elastic Net: starting the full development, automatic lock, test and reports.)
echo First use prepares pinned dependencies in an independent environment.
if exist ".venv\Scripts\python.exe" goto install
where py.exe >nul 2>&1
if errorlevel 1 goto python_path
py -3.11 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 goto python_path
py -3.11 -m venv .venv
if errorlevel 1 goto failed
goto install
:python_path
python -c "import sys, struct; sys.exit(not (sys.version_info >= (3, 11) and struct.calcsize('P') == 8))" >nul 2>&1
if errorlevel 1 (
    echo Install 64-bit Python 3.11 with PATH enabled, then run this file again.
    goto failed
)
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -c "from scripts.market_state.experiments.runtime import environment; environment()" >nul 2>&1
if not errorlevel 1 goto ready
if exist "wheels\*.whl" (
    ".venv\Scripts\python.exe" -c "import sys; assert sys.version_info[:2] == (3, 11)" >nul 2>&1
    if not errorlevel 1 goto offline_install
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-experiments.txt
if errorlevel 1 goto failed
goto ready
:offline_install
".venv\Scripts\python.exe" -m pip install --no-index --find-links wheels --disable-pip-version-check -r requirements-experiments.txt
if errorlevel 1 goto failed
:ready
if exist "package.manifest.json" (
    ".venv\Scripts\python.exe" -m scripts.market_state.experiments.portable --verify .
    if errorlevel 1 goto failed
)
if /I "%MLEC_ACTION%"=="CHECK" goto check
if /I "%MLEC_ACTION%"=="TECHNICAL" goto technical
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launchers\run_elastic_net.ps1" -Python "%~dp0.venv\Scripts\python.exe" %*
if errorlevel 1 goto failed
echo Complete. Results are under the results folder, unless OutputRoot was supplied.
if not defined MLEC_NO_PAUSE pause
exit /b 0
:check
".venv\Scripts\python.exe" -m scripts.market_state.experiments preflight --model elastic_net %*
if errorlevel 1 goto failed
echo Checks passed. No supervised fitting was started.
if not defined MLEC_NO_PAUSE pause
exit /b 0
:technical
".venv\Scripts\python.exe" -m scripts.market_state.experiments.technical --quick --execute --destination reports\model_build\elastic_net\quick_technical.json %*
if errorlevel 1 goto failed
echo Short real technical check passed. No formal B+C experiment was started.
if not defined MLEC_NO_PAUSE pause
exit /b 0
:failed
echo Stopped. Read the error above. After fixing the environment, run this file again to resume.
if not defined MLEC_NO_PAUSE pause
exit /b 1
