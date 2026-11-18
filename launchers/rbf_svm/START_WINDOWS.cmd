@echo off
setlocal
cd /d "%~dp0"
if not exist "config\experiments\rbf_svm.yaml" cd /d "%~dp0..\.."
echo MLEC RBF-SVM: starting this file authorizes real B - lock - C training.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "launchers\bootstrap_rbf_svm.ps1" %*
if errorlevel 1 (
    echo Stopped. Keep all results. Fix the reported environment or task error and restart to resume.
    pause
    exit /b 1
)
echo Complete. Return the entire results\rbf_svm\run_id directory.
pause
