param(
    [switch]$ConExtraccion,
    [switch]$InstalarArranque
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Find-Python {
    $candidates = @("py", "python")
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            return $candidate
        }
    }
    throw "No se encontro Python. Instala Python 3.12+ para Windows y vuelve a ejecutar este instalador."
}

$Python = Find-Python

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Step "Creando entorno virtual .venv"
    if ($Python -eq "py") {
        & py -3 -m venv .venv
    } else {
        & python -m venv .venv
    }
} else {
    Write-Step "Entorno virtual encontrado"
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

Write-Step "Actualizando pip"
& $VenvPython -m pip install --upgrade pip

Write-Step "Instalando dependencias base"
& $VenvPython -m pip install -r requirements.txt

if ($ConExtraccion) {
    Write-Step "Instalando dependencias opcionales de extraccion"
    & $VenvPython -m pip install -r requirements-extraccion.txt
}

Write-Step "Instalando Chromium para Playwright"
& $VenvPython -m playwright install chromium

if (-not (Test-Path ".env")) {
    Write-Step "Creando .env desde .env.example"
    Copy-Item ".env.example" ".env"
}

Write-Step "Verificando app"
& $VenvPython -m py_compile corrector_agente.py interfaz_app.py

if ($InstalarArranque) {
    Write-Step "Instalando arranque automatico en Windows"
    & $VenvPython interfaz_app.py --install-startup
}

Write-Host ""
Write-Host "Instalacion completada." -ForegroundColor Green
Write-Host "Para iniciar la app en bandeja: .\iniciar_app_windows.cmd"
