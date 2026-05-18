param(
    [string]$Salida,
    [switch]$AbrirCarpeta,
    [switch]$ConservarTemporal
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-AppVersion {
    $VersionPath = Join-Path $Root "VERSION"
    if (Test-Path -LiteralPath $VersionPath) {
        return (Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8).Trim()
    }
    return "0.0.0-local"
}

function Find-IExpress {
    $candidates = @(
        (Join-Path $env:SystemRoot "System32\iexpress.exe"),
        (Join-Path $env:SystemRoot "SysWOW64\iexpress.exe"),
        (Get-Command "iexpress.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "No se encontro IExpress en Windows. Usa crear_paquete_windows.cmd o instala Inno Setup para crear un instalador EXE alternativo."
}

function Quote-SedValue([string]$Value) {
    return $Value -replace '"', '""'
}

$Version = Get-AppVersion
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $Salida) {
    $Salida = [Environment]::GetFolderPath("Desktop")
}

$OutputRoot = [IO.Path]::GetFullPath($Salida)
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$BuildRoot = Join-Path $Root ".tmp_setup_build"
$PackageOut = Join-Path $BuildRoot "paquete"
$SfxSource = Join-Path $BuildRoot "sfx_source"
$SedPath = Join-Path $BuildRoot "corrector_carm_setup.sed"
$SetupName = "Corrector_CARM_${Version}_Setup_$Stamp.exe"
$SetupPath = Join-Path $OutputRoot $SetupName

if (Test-Path -LiteralPath $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageOut -Force | Out-Null
New-Item -ItemType Directory -Path $SfxSource -Force | Out-Null

try {
    Write-Step "Creando ZIP limpio del paquete guiado"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "crear_paquete_windows.ps1") -Salida $PackageOut
    if ($LASTEXITCODE -ne 0) {
        throw "crear_paquete_windows.ps1 fallo con codigo $LASTEXITCODE"
    }

    $PayloadZip = Get-ChildItem -LiteralPath $PackageOut -Filter "Corrector_CARM_*_guiado_*.zip" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $PayloadZip) {
        throw "No se encontro el ZIP del paquete guiado generado."
    }

    Copy-Item -LiteralPath $PayloadZip.FullName -Destination (Join-Path $SfxSource "payload.zip") -Force

    $Bootstrap = @'
@echo off
setlocal EnableExtensions
title Instalador Corrector CARM
set "SETUP_ROOT=%TEMP%\CorrectorCARM_Setup_%RANDOM%_%RANDOM%"
mkdir "%SETUP_ROOT%" >nul 2>nul
if errorlevel 1 (
  echo No se pudo crear carpeta temporal de instalacion.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~dp0payload.zip' -DestinationPath '%SETUP_ROOT%' -Force"
if errorlevel 1 (
  echo No se pudo extraer el paquete de instalacion.
  pause
  exit /b 1
)
set "APPDIR="
for /d %%D in ("%SETUP_ROOT%\Corrector_CARM_*") do (
  if exist "%%~fD\INSTALAR_CORRECTOR_CARM.cmd" set "APPDIR=%%~fD"
)
if not defined APPDIR (
  echo No se encontro el instalador guiado dentro del paquete extraido.
  pause
  exit /b 1
)
cd /d "%APPDIR%"
call INSTALAR_CORRECTOR_CARM.cmd
set "EXITCODE=%ERRORLEVEL%"
exit /b %EXITCODE%
'@
    Set-Content -LiteralPath (Join-Path $SfxSource "instalar_corrector_carm_setup.cmd") -Value $Bootstrap -Encoding ASCII

    $IExpress = Find-IExpress
    Write-Step "Creando instalador EXE autoextraible"
    $Sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3

[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName="$(Quote-SedValue $SetupPath)"
FriendlyName="Corrector CARM"
AppLaunched=instalar_corrector_carm_setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles

[SourceFiles]
SourceFiles0="$(Quote-SedValue ($SfxSource + "\"))"

[SourceFiles0]
%FILE0%=
%FILE1%=

[Strings]
FILE0="payload.zip"
FILE1="instalar_corrector_carm_setup.cmd"
"@
    Set-Content -LiteralPath $SedPath -Value $Sed -Encoding ASCII
    & $IExpress /N /Q $SedPath
    if ($LASTEXITCODE -ne 0) {
        throw "IExpress fallo con codigo $LASTEXITCODE"
    }
    $Deadline = (Get-Date).AddSeconds(20)
    while (-not (Test-Path -LiteralPath $SetupPath) -and (Get-Date) -lt $Deadline) {
        Start-Sleep -Milliseconds 300
    }
    if (-not (Test-Path -LiteralPath $SetupPath)) {
        throw "IExpress termino sin crear $SetupPath"
    }

    $SizeMb = [math]::Round((Get-Item -LiteralPath $SetupPath).Length / 1MB, 2)
    Write-Host ""
    Write-Host "Instalador EXE creado:" -ForegroundColor Green
    Write-Host $SetupPath
    Write-Host "Tamano MB: $SizeMb"
    Write-Host ""
    Write-Host "Nota: al no estar firmado digitalmente, Windows SmartScreen puede avisar de editor desconocido." -ForegroundColor Yellow
    if ($AbrirCarpeta) {
        Start-Process $OutputRoot
    }
} finally {
    if (-not $ConservarTemporal -and (Test-Path -LiteralPath $BuildRoot)) {
        Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
