@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo No existe .venv. Ejecuta primero instalar_windows.cmd
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "interfaz_app.py" --tray --no-browser
echo Corrector CARM iniciado en bandeja.
