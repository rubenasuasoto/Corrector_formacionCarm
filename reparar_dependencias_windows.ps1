param(
    [switch]$ConExtraccion,
    [switch]$ReinstalarChromium,
    [switch]$LimpiarPlaywrightLock,
    [switch]$SinVerificacion
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [string]$Description,
        [scriptblock]$Command
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description fallo con codigo $LASTEXITCODE"
    }
}

function Find-Python {
    if (Test-Path ".venv\Scripts\python.exe") {
        return (Join-Path $Root ".venv\Scripts\python.exe")
    }
    $candidates = @("py", "python")
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            return $candidate
        }
    }
    throw "No se encontro Python ni .venv. Ejecuta instalar_windows.cmd primero."
}

function Test-PlaywrightChromiumInstalled {
    $MsPlaywright = Join-Path $env:LOCALAPPDATA "ms-playwright"
    if (-not (Test-Path $MsPlaywright)) {
        return $false
    }
    return [bool](Get-ChildItem -LiteralPath $MsPlaywright -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Remove-PlaywrightLock {
    $LockPath = Join-Path $env:LOCALAPPDATA "ms-playwright\__dirlock"
    if (Test-Path $LockPath) {
        Remove-Item -LiteralPath $LockPath -Force
        Write-Host "Lock eliminado: $LockPath" -ForegroundColor Yellow
    } else {
        Write-Host "No habia lock de Playwright." -ForegroundColor Green
    }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Step "Creando entorno virtual .venv"
    $Python = Find-Python
    if ($Python -eq "py") {
        Invoke-Native "Creacion de .venv" { & py -3 -m venv .venv }
    } else {
        Invoke-Native "Creacion de .venv" { & $Python -m venv .venv }
    }
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if ($LimpiarPlaywrightLock) {
    Write-Step "Limpiando lock de Playwright"
    Remove-PlaywrightLock
}

Write-Step "Reinstalando dependencias base"
Invoke-Native "Actualizacion de pip" { & $VenvPython -m pip install --upgrade pip }
Invoke-Native "Reinstalacion de dependencias base" { & $VenvPython -m pip install --upgrade --force-reinstall -r requirements.txt }

if ($ConExtraccion) {
    Write-Step "Reinstalando dependencias opcionales de extraccion"
    Invoke-Native "Reinstalacion de dependencias opcionales" { & $VenvPython -m pip install --upgrade --force-reinstall -r requirements-extraccion.txt }
}

if ($ReinstalarChromium -or -not (Test-PlaywrightChromiumInstalled)) {
    Write-Step "Instalando Chromium para Playwright"
    Invoke-Native "Instalacion de Chromium para Playwright" { & $VenvPython -m playwright install chromium }
} else {
    Write-Step "Chromium de Playwright ya instalado"
}

if (-not $SinVerificacion) {
    Write-Step "Verificando reparacion"
    Invoke-Native "Verificacion de reparacion" { & $VenvPython verificar_app.py --instalacion --sin-prueba-offline }
}

Write-Host ""
Write-Host "Reparacion completada." -ForegroundColor Green
Write-Host "Si Windows habia bloqueado Chromium, prueba de nuevo: .\verificar_app_windows.cmd"
