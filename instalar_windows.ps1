param(
    [switch]$ConExtraccion,
    [switch]$InstalarArranque,
    [switch]$AutoPrepararAlInicio,
    [switch]$CrearAccesoDirecto,
    [switch]$OmitirVerificacion
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
    $candidates = @("py", "python")
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            return $candidate
        }
    }
    throw "No se encontro Python. Instala Python 3.12+ para Windows y vuelve a ejecutar este instalador."
}

function Test-PythonVersion {
    param([string]$PythonCommand)
    $versionText = & $PythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $parts = $versionText.Trim().Split(".")
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 12)) {
        throw "Python 3.12+ requerido. Detectado: $versionText"
    }
}

function New-DesktopShortcut {
    param([string]$Target)
    $Desktop = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path $Desktop "Corrector CARM.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $Target
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.Description = "Iniciar Corrector CARM"
    $Shortcut.Save()
    Write-Host "Acceso directo creado: $ShortcutPath" -ForegroundColor Green
}

function Test-PlaywrightChromiumInstalled {
    $MsPlaywright = Join-Path $env:LOCALAPPDATA "ms-playwright"
    if (-not (Test-Path $MsPlaywright)) {
        return $false
    }
    return [bool](Get-ChildItem -LiteralPath $MsPlaywright -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Select-Object -First 1)
}

$Python = Find-Python
Test-PythonVersion -PythonCommand $Python

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Step "Creando entorno virtual .venv"
    if ($Python -eq "py") {
        Invoke-Native "Creacion de .venv" { & py -3 -m venv .venv }
    } else {
        Invoke-Native "Creacion de .venv" { & python -m venv .venv }
    }
} else {
    Write-Step "Entorno virtual encontrado"
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

Write-Step "Actualizando pip"
Invoke-Native "Actualizacion de pip" { & $VenvPython -m pip install --upgrade pip }

Write-Step "Instalando dependencias base"
Invoke-Native "Instalacion de dependencias base" { & $VenvPython -m pip install -r requirements.txt }

if ($ConExtraccion) {
    Write-Step "Instalando dependencias opcionales de extraccion"
    Invoke-Native "Instalacion de dependencias opcionales" { & $VenvPython -m pip install -r requirements-extraccion.txt }
}

if (Test-PlaywrightChromiumInstalled) {
    Write-Step "Chromium de Playwright ya instalado"
} else {
    Write-Step "Instalando Chromium para Playwright"
    Invoke-Native "Instalacion de Chromium para Playwright" { & $VenvPython -m playwright install chromium }
}

if (-not (Test-Path ".env")) {
    Write-Step "Creando .env desde .env.example"
    Copy-Item ".env.example" ".env"
}

Write-Step "Verificando app"
Invoke-Native "Compilacion de la app" { & $VenvPython -m py_compile corrector_agente.py interfaz_app.py }

if ($InstalarArranque) {
    Write-Step "Instalando arranque automatico en Windows"
    if ($AutoPrepararAlInicio) {
        Invoke-Native "Instalacion de arranque automatico" { & $VenvPython interfaz_app.py --install-startup --install-startup-auto-correct }
    } else {
        Invoke-Native "Instalacion de arranque automatico" { & $VenvPython interfaz_app.py --install-startup }
    }
}

if ($CrearAccesoDirecto) {
    Write-Step "Creando acceso directo en el escritorio"
    New-DesktopShortcut -Target (Join-Path $Root "iniciar_app_windows.cmd")
}

if (-not $OmitirVerificacion) {
    Write-Step "Verificando instalacion"
    Invoke-Native "Verificacion de instalacion" { & $VenvPython verificar_app.py --instalacion }
}

Write-Host ""
Write-Host "Instalacion completada." -ForegroundColor Green
Write-Host "Para iniciar la app en bandeja: .\iniciar_app_windows.cmd"
Write-Host "Para verificar todo tras configurar CARM: .\verificar_app_windows.cmd"
