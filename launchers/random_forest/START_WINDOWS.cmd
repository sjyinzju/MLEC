@echo off
setlocal
cd /d "%~dp0"
if not exist "config\experiments\random_forest.yaml" cd /d "%~dp0..\.."
if not defined MLEC_RF_ACTION set "MLEC_RF_ACTION=START"
echo MLEC Random Forest action: %MLEC_RF_ACTION% - CHECK does not train.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "launchers\bootstrap_random_forest.ps1" -Action "%MLEC_RF_ACTION%" %*
if errorlevel 1 (
    echo Stopped. Keep all results. Fix the reported environment or task error and restart to resume.
    if not defined MLEC_NO_PAUSE pause
    exit /b 1
)
echo Action completed. Formal results, if explicitly run, are under results\random_forest\run_id.
if not defined MLEC_NO_PAUSE pause
