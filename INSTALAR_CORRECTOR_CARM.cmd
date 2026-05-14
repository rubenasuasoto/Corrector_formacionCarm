@echo off
setlocal
cd /d "%~dp0"
title Instalador Corrector CARM
echo.
echo ========================================
echo        Instalador Corrector CARM
echo ========================================
echo.
echo Este asistente preparara la app, instalara dependencias,
echo creara accesos directos y dejara el panel listo para abrir.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_windows.ps1" -ConExtraccion -CrearAccesoDirecto %*
if errorlevel 1 (
    echo.
    echo La instalacion no se ha completado correctamente.
    pause
    exit /b 1
)
echo.
echo Instalacion completada.
echo Puedes abrir la app desde el acceso directo "Corrector CARM".
pause
