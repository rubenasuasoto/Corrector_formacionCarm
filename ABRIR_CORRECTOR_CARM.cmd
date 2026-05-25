@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0Corrector CARM.exe" (
  start "" "%~dp0Corrector CARM.exe" %*
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_app_windows.ps1" -AbrirNavegador %*
if errorlevel 1 pause
