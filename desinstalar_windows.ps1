param(
    [switch]$EliminarDatos,
    [switch]$Silencioso,
    [switch]$PermitirRepositorio
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootFull = [IO.Path]::GetFullPath($Root)
$AppName = "Corrector CARM"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Corrector CARM"

function Write-Step($Message) {
    if (-not $Silencioso) {
        Write-Host ""
        Write-Host "==> $Message" -ForegroundColor Cyan
    }
}

function Remove-IfExists([string]$Path) {
    if ($Path -and (Test-Path -LiteralPath $Path)) {
        Remove-Item -LiteralPath $Path -Force -Recurse -ErrorAction SilentlyContinue
    }
}

function Read-AppConfig {
    $configPath = Join-Path $RootFull ".corrector_app.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Stop-AppProcesses {
    Write-Step "Cerrando procesos de Corrector CARM"
    try {
        Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object {
                ($_.CommandLine -like "*interfaz_app.py*" -or $_.CommandLine -like "*corrector_agente.py*" -or $_.CommandLine -like "*Corrector CARM.exe*") -and
                ($_.CommandLine -like "*$RootFull*")
            } |
            ForEach-Object {
                try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
            }
    } catch {
        if (-not $Silencioso) {
            Write-Host "Aviso: no se pudieron consultar procesos automaticamente. Cierra la app si sigue abierta." -ForegroundColor Yellow
        }
    }
}

function Remove-Shortcuts {
    Write-Step "Eliminando accesos directos e inicio automatico"
    $desktop = [Environment]::GetFolderPath("Desktop")
    $programs = [Environment]::GetFolderPath("Programs")
    $startup = [Environment]::GetFolderPath("Startup")
    Remove-IfExists (Join-Path $desktop "Corrector CARM.lnk")
    Remove-IfExists (Join-Path $programs "Corrector CARM")
    Remove-IfExists (Join-Path $startup "Corrector CARM.cmd")
}

function Remove-UninstallEntry {
    Write-Step "Eliminando registro de Aplicaciones instaladas"
    if (Test-Path -LiteralPath $UninstallKey) {
        Remove-Item -LiteralPath $UninstallKey -Force -Recurse -ErrorAction SilentlyContinue
    }
}

function Remove-AppFolder([string]$PathToRemove) {
    if (-not (Test-Path -LiteralPath $PathToRemove)) {
        return
    }
    if ((Test-Path -LiteralPath (Join-Path $PathToRemove ".git")) -and -not $PermitirRepositorio) {
        throw "La carpeta parece un repositorio Git. No se borra para evitar perder codigo fuente. Usa -PermitirRepositorio si sabes lo que haces."
    }
    Write-Step "Eliminando carpeta de instalacion"
    Set-Location -LiteralPath ([IO.Path]::GetTempPath())
    Remove-Item -LiteralPath $PathToRemove -Force -Recurse -ErrorAction Stop
}

if (-not $Silencioso) {
    Write-Host ""
    Write-Host "Desinstalador $AppName" -ForegroundColor Cyan
    Write-Host "Instalacion: $RootFull"
    if (-not $EliminarDatos) {
        Write-Host "Los datos locales no se borraran salvo que uses -EliminarDatos." -ForegroundColor Yellow
    }
}

$config = Read-AppConfig
$dataPaths = @()
if ($config) {
    foreach ($value in @($config.pendientes_dir, $config.temporal_dir, $config.courses_dir)) {
        if ($value) {
            $fullPath = [IO.Path]::GetFullPath([string]$value)
            if ($dataPaths -notcontains $fullPath) {
                $dataPaths += $fullPath
            }
        }
    }
}

Stop-AppProcesses
Remove-Shortcuts
Remove-UninstallEntry

if ($EliminarDatos) {
    foreach ($dataPath in $dataPaths) {
        if ($dataPath -and (Test-Path -LiteralPath $dataPath)) {
            Write-Step "Eliminando datos locales: $dataPath"
            Remove-Item -LiteralPath $dataPath -Force -Recurse -ErrorAction SilentlyContinue
        }
    }
}

Remove-AppFolder $RootFull

if (-not $Silencioso) {
    Write-Host ""
    Write-Host "Corrector CARM desinstalado." -ForegroundColor Green
    if (-not $EliminarDatos -and $dataPaths.Count -gt 0) {
        Write-Host "Datos conservados:" -ForegroundColor Yellow
        $dataPaths | ForEach-Object { Write-Host " - $_" }
    }
}
