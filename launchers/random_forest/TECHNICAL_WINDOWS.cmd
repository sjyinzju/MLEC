@echo off
setlocal
set "MLEC_RF_ACTION=TECHNICAL"
call "%~dp0START_WINDOWS.cmd" %*
exit /b %errorlevel%
