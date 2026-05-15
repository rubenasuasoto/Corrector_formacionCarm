@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_launcher_windows.ps1" %*
if errorlevel 1 pause
