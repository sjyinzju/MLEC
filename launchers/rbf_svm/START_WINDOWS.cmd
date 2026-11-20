@echo off
setlocal
cd /d "%~dp0"
if not exist "config\experiments\rbf_svm.yaml" cd /d "%~dp0..\.."
if not defined MLEC_ACTION set "MLEC_ACTION=START"
echo MLEC RBF-SVM action: %MLEC_ACTION% - CHECK does not train.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "launchers\bootstrap_rbf_svm.ps1" -Action "%MLEC_ACTION%" %*
if errorlevel 1 (
    echo Stopped. Keep all results. Fix the reported environment or task error and restart to resume.
    if not defined MLEC_NO_PAUSE pause
    exit /b 1
)
echo Action completed. Formal results, if explicitly run, are under results\rbf_svm\run_id.
if not defined MLEC_NO_PAUSE pause
