@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No existe .venv. Ejecuta primero instalar_windows.cmd
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "verificar_app.py" %*
set EXITCODE=%ERRORLEVEL%
pause
exit /b %EXITCODE%
