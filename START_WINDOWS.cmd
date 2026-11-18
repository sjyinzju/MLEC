@echo off
setlocal
cd /d "%~dp0"
echo MLEC Elastic Net: full development, automatic lock, test and reports.
echo First use installs pinned dependencies. Starting this file authorizes training.
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
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-experiments.txt
if errorlevel 1 goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launchers\run_elastic_net.ps1" -Python "%~dp0.venv\Scripts\python.exe" %*
if errorlevel 1 goto failed
echo Complete. Results are under the results folder, unless OutputRoot was supplied.
pause
exit /b 0
:failed
echo Stopped. Read the error above. After fixing the environment, run this file again to resume.
pause
exit /b 1
