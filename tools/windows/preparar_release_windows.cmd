@echo off
setlocal
set "TOOLS_DIR=%~dp0"
cd /d "%TOOLS_DIR%..\.."
if not exist ".venv\Scripts\python.exe" (
  echo No existe .venv. Ejecuta primero instalar_windows.cmd
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "%TOOLS_DIR%preparar_release.py" %*
set EXITCODE=%ERRORLEVEL%
pause
exit /b %EXITCODE%
