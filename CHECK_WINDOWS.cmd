@echo off
setlocal
set "MLEC_ACTION=CHECK"
call "%~dp0START_WINDOWS.cmd" %*
exit /b %errorlevel%
