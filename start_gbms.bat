@echo off
cd /d "%~dp0"

REM Run the app from a hidden PowerShell process so the user sees no black console window.
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start_gbms.ps1"
exit /b %ERRORLEVEL%
