param(
    [switch]$AbrirNavegador,
    [switch]$AutoPreparar,
    [switch]$SinEscaneoInicial,
    [int]$Puerto = 8765
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

function Test-LocalPanel {
    param([int]$Port)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    Write-Host "No existe .venv. Ejecuta primero: .\instalar_windows.cmd" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $Pythonw)) {
    Write-Host "No existe pythonw.exe en .venv. Ejecuta: .\reparar_dependencias_windows.cmd" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "No existe .env. Creo una plantilla desde .env.example; despues abre la app y configura credenciales CARM." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

if (Test-LocalPanel -Port $Puerto) {
    Write-Host "Corrector CARM ya esta abierto en http://127.0.0.1:$Puerto" -ForegroundColor Green
    if ($AbrirNavegador) {
        Start-Process "http://127.0.0.1:$Puerto"
    }
    exit 0
}

Write-Step "Comprobando archivos principales"
Invoke-Native "Compilacion rapida" { & $Python -m py_compile interfaz_app.py corrector_agente.py }

$ArgsList = @(
    "interfaz_app.py",
    "--tray",
    "--host", "127.0.0.1",
    "--port", "$Puerto"
)

if (-not $AbrirNavegador) {
    $ArgsList += "--no-browser"
}
if ($AutoPreparar) {
    $ArgsList += "--auto-correct"
}
if ($SinEscaneoInicial) {
    $ArgsList += "--no-startup-scan"
}

Write-Step "Iniciando Corrector CARM"
Start-Process -FilePath $Pythonw -ArgumentList $ArgsList -WorkingDirectory $Root -WindowStyle Hidden

Write-Host ""
Write-Host "Corrector CARM iniciado." -ForegroundColor Green
Write-Host "Si no ves icono de bandeja, abre el panel desde la notificacion o ejecuta: .\verificar_app_windows.cmd"
