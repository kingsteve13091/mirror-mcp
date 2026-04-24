@echo off
setlocal
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File ".\scripts\install_system.ps1" %*
exit /b %ERRORLEVEL%
