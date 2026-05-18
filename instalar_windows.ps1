param(
    [switch]$ConExtraccion,
    [switch]$InstalarOCR,
    [switch]$InstalarArranque,
    [switch]$AutoPrepararAlInicio,
    [switch]$PrepararCodex,
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

function New-AppShortcut {
    param([string]$Target)
    $ShortcutPath = $Target
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $LauncherExe = Join-Path $Root "Corrector CARM.exe"
    if (Test-Path -LiteralPath $LauncherExe) {
        $Shortcut.TargetPath = $LauncherExe
    } else {
        $Shortcut.TargetPath = Join-Path $Root "ABRIR_CORRECTOR_CARM.cmd"
    }
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.Description = "Iniciar Corrector CARM"
    $IconPath = Join-Path $Root "assets\corrector_carm.ico"
    if (Test-Path -LiteralPath $IconPath) {
        $Shortcut.IconLocation = $IconPath
    }
    $Shortcut.Save()
    Write-Host "Acceso directo creado: $ShortcutPath" -ForegroundColor Green
}

function New-AppShortcuts {
    $Desktop = [Environment]::GetFolderPath("Desktop")
    New-AppShortcut -Target (Join-Path $Desktop "Corrector CARM.lnk")

    $Programs = [Environment]::GetFolderPath("Programs")
    $StartFolder = Join-Path $Programs "Corrector CARM"
    New-Item -ItemType Directory -Path $StartFolder -Force | Out-Null
    New-AppShortcut -Target (Join-Path $StartFolder "Corrector CARM.lnk")
}

function Register-UninstallEntry {
    $VersionPath = Join-Path $Root "VERSION"
    $Version = "0.0.0-local"
    if (Test-Path -LiteralPath $VersionPath) {
        $Version = (Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8).Trim()
    }
    $UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Corrector CARM"
    $UninstallScript = Join-Path $Root "desinstalar_windows.ps1"
    $IconPath = Join-Path $Root "assets\corrector_carm.ico"
    New-Item -Path $UninstallKey -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name "DisplayName" -Value "Corrector CARM" -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name "DisplayVersion" -Value $Version -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name "Publisher" -Value "Corrector CARM Local" -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name "InstallLocation" -Value $Root -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name "UninstallString" -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UninstallScript`"" -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name "QuietUninstallString" -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UninstallScript`" -Silencioso" -PropertyType String -Force | Out-Null
    if (Test-Path -LiteralPath $IconPath) {
        New-ItemProperty -Path $UninstallKey -Name "DisplayIcon" -Value $IconPath -PropertyType String -Force | Out-Null
    }
    New-ItemProperty -Path $UninstallKey -Name "NoModify" -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name "NoRepair" -Value 1 -PropertyType DWord -Force | Out-Null
    Write-Host "Entrada de desinstalacion registrada en Aplicaciones instaladas." -ForegroundColor Green
}

function Test-PlaywrightChromiumInstalled {
    $MsPlaywright = Join-Path $env:LOCALAPPDATA "ms-playwright"
    if (-not (Test-Path $MsPlaywright)) {
        return $false
    }
    return [bool](Get-ChildItem -LiteralPath $MsPlaywright -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Find-CodexDesktop {
    $pkg = Get-AppxPackage -Name "OpenAI.Codex" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pkg) {
        return $pkg.InstallLocation
    }
    return ""
}

function Find-CodexDesktopCli {
    $npmCodex = Join-Path $env:APPDATA "npm\codex.cmd"
    $candidates = @(
        $npmCodex,
        (Get-Command "codex.cmd" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
        (Get-Command "codex" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate) -and $candidate -notmatch "\\.vscode\\extensions\\openai\.chatgpt-" -and $candidate -notmatch "\.ps1$") {
            return $candidate
        }
    }
    return ""
}

function Find-NodeCommand {
    $candidates = @(
        (Get-Command "node.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
        (Join-Path $env:ProgramFiles "nodejs\node.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return ""
}

function Find-NpmCommand {
    $candidates = @(
        (Get-Command "npm.cmd" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
        (Join-Path $env:ProgramFiles "nodejs\npm.cmd")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return ""
}

function Install-NodeJsLts {
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "No se encontro winget. Instala Node.js LTS manualmente desde https://nodejs.org y vuelve a ejecutar el instalador."
    }

    Write-Host "Node.js LTS no detectado. Instalando con winget..." -ForegroundColor Yellow
    Invoke-Native "Instalacion de Node.js LTS" {
        & $winget.Source install --id OpenJS.NodeJS.LTS --source winget --accept-package-agreements --accept-source-agreements --silent
    }

    $nodePath = Join-Path $env:ProgramFiles "nodejs"
    if (Test-Path -LiteralPath $nodePath) {
        $env:Path = "$nodePath;$env:Path"
    }
}

function Install-CodexCli {
    param([string]$NpmCommand)

    Write-Host "Instalando/actualizando Codex CLI oficial con npm..." -ForegroundColor Yellow
    Invoke-Native "Instalacion de Codex CLI" {
        & $NpmCommand install -g @openai/codex
    }

    $npmBin = Join-Path $env:APPDATA "npm"
    if (Test-Path -LiteralPath $npmBin) {
        $env:Path = "$npmBin;$env:Path"
    }
}

function Ensure-CodexEnvironment {
    Write-Step "Preparando Codex CLI sin API"

    $node = Find-NodeCommand
    if (-not $node) {
        Install-NodeJsLts
        $node = Find-NodeCommand
    }
    if ($node) {
        try {
            $nodeVersion = (& $node --version).Trim()
            Write-Host "Node.js detectado: $nodeVersion ($node)" -ForegroundColor Green
        } catch {
            Write-Host "Node.js detectado, pero no se pudo leer la version: $node" -ForegroundColor Yellow
        }
        $nodeDir = Split-Path -Parent $node
        if ($nodeDir -and (Test-Path -LiteralPath $nodeDir)) {
            $env:Path = "$nodeDir;$env:Path"
        }
    } else {
        throw "No se pudo preparar Node.js LTS."
    }

    $npm = Find-NpmCommand
    if (-not $npm) {
        throw "No se encontro npm tras preparar Node.js. Abre una terminal nueva o reinstala Node.js LTS."
    }
    try {
        $npmVersion = (& $npm --version).Trim()
        Write-Host "npm detectado: $npmVersion ($npm)" -ForegroundColor Green
    } catch {
        Write-Host "npm detectado, pero no se pudo leer la version: $npm" -ForegroundColor Yellow
    }

    $codexCli = Find-CodexDesktopCli
    if (-not $codexCli) {
        Install-CodexCli -NpmCommand $npm
        $codexCli = Find-CodexDesktopCli
    }

    if ($codexCli) {
        Write-Host "Codex CLI oficial detectado: $codexCli" -ForegroundColor Green
        try {
            & $codexCli --version | Out-Host
        } catch {
            Write-Host "Codex CLI instalado, pero no se pudo leer la version." -ForegroundColor Yellow
        }
        try {
            $loginStatus = & $codexCli login status 2>&1
            $loginExit = $LASTEXITCODE
            $loginStatus | Out-Host
            if ($loginExit -eq 0) {
                Write-Host "Codex listo: sesion detectada." -ForegroundColor Green
            } else {
                Write-Host "Codex CLI listo, pero falta iniciar sesion para usar el modo sin API." -ForegroundColor Yellow
                Write-Host "Despues de instalar, abre una terminal y ejecuta: codex login" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "Codex CLI instalado. Inicia sesion con ChatGPT ejecutando: codex login" -ForegroundColor Yellow
        }
    } else {
        throw "No se encontro codex.cmd tras instalar @openai/codex."
    }
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

if ($InstalarOCR) {
    Write-Step "Instalando OCR para PDF escaneados e imagenes"
    try {
        $ocrScript = Join-Path $Root "instalar_ocr_windows.ps1"
        if (Test-Path -LiteralPath $ocrScript) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $ocrScript
            if ($LASTEXITCODE -ne 0) {
                Write-Host "No se pudo instalar OCR automaticamente. La app seguira funcionando y marcara esos archivos como revision manual." -ForegroundColor Yellow
            }
        } else {
            Write-Host "No se encontro instalar_ocr_windows.ps1; se omite OCR." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "No se pudo instalar OCR automaticamente. Detalle: $_" -ForegroundColor Yellow
    }
}

if ($PrepararCodex) {
    try {
        $CodexDesktop = Find-CodexDesktop
        if ($CodexDesktop) {
            Write-Host "Codex Desktop detectado: $CodexDesktop" -ForegroundColor Green
        }
        Ensure-CodexEnvironment
    } catch {
        Write-Host "No se pudo preparar Codex automaticamente. La app seguira funcionando con API o modo prompt manual." -ForegroundColor Yellow
        Write-Host "Detalle: $_" -ForegroundColor Yellow
    }
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

if (Test-Path ".\crear_launcher_windows.ps1") {
    Write-Step "Preparando lanzador de escritorio"
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File ".\crear_launcher_windows.ps1"
    } catch {
        Write-Host "No se pudo crear el lanzador .exe; se usaran los accesos .cmd. Detalle: $_" -ForegroundColor Yellow
    }
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
    Write-Step "Creando accesos directos"
    New-AppShortcuts
}

Write-Step "Registrando desinstalador de Windows"
Register-UninstallEntry

if (-not $OmitirVerificacion) {
    Write-Step "Verificando instalacion"
    Invoke-Native "Verificacion de instalacion" { & $VenvPython verificar_app.py --instalacion }
}

Write-Host ""
Write-Host "Instalacion completada." -ForegroundColor Green
Write-Host "Para abrir el panel: .\ABRIR_CORRECTOR_CARM.cmd"
Write-Host "Para iniciar solo en bandeja: .\iniciar_app_windows.cmd"
Write-Host "Para verificar todo tras configurar CARM: .\verificar_app_windows.cmd"
if ($PrepararCodex) {
    Write-Host "Modo sin API: si Codex no tiene sesion iniciada, ejecuta codex login antes de corregir con CLI." -ForegroundColor Yellow
}
