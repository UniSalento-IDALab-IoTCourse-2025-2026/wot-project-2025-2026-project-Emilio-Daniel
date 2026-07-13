@echo off
setlocal

cd /d "%~dp0\..\.."

echo Avvio diagnosi Dashboard IoT...
echo Cartella progetto: %CD%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\Script\test\diagnose_dashboard_data.ps1"

echo.
echo Diagnosi terminata. Premi un tasto per chiudere.
pause >nul
