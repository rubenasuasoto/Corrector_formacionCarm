param(
    [string]$Salida,
    [switch]$AbrirCarpeta
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
        return (Get-Content -LiteralPath $VersionPath -Raw).Trim()
    }
    return "0.0.0-local"
}

function Copy-ReleaseFile {
    param(
        [string]$RelativePath,
        [string]$DestinationRoot
    )

    $Source = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        return
    }

    $Target = Join-Path $DestinationRoot $RelativePath
    $Parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Path $Parent -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Target -Force
}

function Assert-NoSensitiveArtifacts {
    param([string]$DestinationRoot)

    $Sensitive = Get-ChildItem -LiteralPath $DestinationRoot -Recurse -Force | Where-Object {
        $_.Name -eq ".env" -or
        $_.FullName -match "\\.venv\\" -or
        $_.FullName -match "\\logs_correcciones\\" -or
        $_.FullName -match "\\respuestas_extraidas\\" -or
        $_.FullName -match "\\cache_carm\\" -or
        $_.FullName -match "\\__pycache__\\"
    }

    if ($Sensitive) {
        $List = ($Sensitive | ForEach-Object { $_.FullName }) -join "`n"
        throw "El paquete contiene artefactos sensibles o generados:`n$List"
    }
}

$Version = Get-AppVersion
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $Salida) {
    $Salida = [Environment]::GetFolderPath("Desktop")
}

$OutputRoot = [IO.Path]::GetFullPath($Salida)
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$PackageName = "Corrector_CARM_${Version}_guiado_$Stamp"
$PackageDir = Join-Path $OutputRoot $PackageName
$PackageZip = "$PackageDir.zip"

Write-Step "Creando paquete guiado"
New-Item -ItemType Directory -Path $PackageDir | Out-Null

$TrackedFiles = git ls-files
$ExtraReleaseFiles = @(
    "INSTALAR_CORRECTOR_CARM.cmd",
    "ABRIR_CORRECTOR_CARM.cmd",
    "crear_paquete_windows.cmd",
    "crear_paquete_windows.ps1",
    "assets/corrector_carm.ico",
    "assets/corrector_carm.png"
)

$Files = @($TrackedFiles + $ExtraReleaseFiles) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Sort-Object -Unique

foreach ($File in $Files) {
    Copy-ReleaseFile -RelativePath $File -DestinationRoot $PackageDir
}

$Readme = @"
Corrector CARM $Version

Instalacion guiada en otro Windows:
1. Descomprime esta carpeta.
2. Haz doble clic en INSTALAR_CORRECTOR_CARM.cmd.
3. El instalador prepara dependencias y crea accesos directos.
4. Abre Corrector CARM desde el Escritorio o el menu Inicio.
5. La primera vez, configura credenciales CARM desde la interfaz si faltan.

Entradas utiles:
- INSTALAR_CORRECTOR_CARM.cmd: instalacion guiada recomendada.
- ABRIR_CORRECTOR_CARM.cmd: abre el panel de la app.
- verificar_app_windows.cmd: diagnostico local.

Notas:
- No incluye .env real, cache, logs, entregas ni correcciones generadas.
- La app escucha solo en 127.0.0.1.
- La subida a CARM es asistida: el docente revisa y guarda manualmente.
"@
Set-Content -LiteralPath (Join-Path $PackageDir "LEEME_INSTALACION.txt") -Value $Readme -Encoding UTF8

$Manifest = [ordered]@{
    nombre = $PackageName
    version = $Version
    creado = (Get-Date).ToString("s")
    origen = $Root
    instalador_principal = "INSTALAR_CORRECTOR_CARM.cmd"
    lanzador_panel = "ABRIR_CORRECTOR_CARM.cmd"
    incluye_secretos = $false
}
$Manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $PackageDir "MANIFIESTO_PAQUETE.json") -Encoding UTF8

Assert-NoSensitiveArtifacts -DestinationRoot $PackageDir

Write-Step "Comprimiendo ZIP"
Compress-Archive -Path $PackageDir -DestinationPath $PackageZip -Force

$FileCount = (Get-ChildItem -LiteralPath $PackageDir -Recurse -File -Force | Measure-Object).Count
$ZipMb = [math]::Round((Get-Item -LiteralPath $PackageZip).Length / 1MB, 2)

Write-Host ""
Write-Host "Paquete creado:" -ForegroundColor Green
Write-Host "Carpeta: $PackageDir"
Write-Host "ZIP:     $PackageZip"
Write-Host "Archivos: $FileCount"
Write-Host "Tamano ZIP MB: $ZipMb"

if ($AbrirCarpeta) {
    Start-Process $OutputRoot
}
