@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_ocr_windows.ps1" %*
exit /b %ERRORLEVEL%
