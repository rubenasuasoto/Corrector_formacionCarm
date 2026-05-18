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
        $_.FullName -match "\\codex_project\\" -or
        $_.FullName -match "\\__pycache__\\"
    }

    if ($Sensitive) {
        $List = ($Sensitive | ForEach-Object { $_.FullName }) -join "`n"
        throw "El paquete contiene artefactos sensibles o generados:`n$List"
    }

    $DevelopmentOnly = @(
        "AGENTS.md",
        "ARQUITECTURA_PROYECTO.md",
        "CIERRE_APP_LOCAL.md",
        "ESTADO_PROYECTO.md",
        "RELEASE_CHECKLIST.md",
        "ROADMAP_DESCARGA_SEGURA.md",
        "preparar_release.py",
        "preparar_release_windows.cmd",
        "preparar_release_windows.ps1",
        ".gitignore"
    )
    $FoundDevelopmentOnly = Get-ChildItem -LiteralPath $DestinationRoot -Recurse -Force | Where-Object {
        $DevelopmentOnly -contains $_.Name
    }

    if ($FoundDevelopmentOnly) {
        $List = ($FoundDevelopmentOnly | ForEach-Object { $_.FullName }) -join "`n"
        throw "El paquete contiene archivos de desarrollo que no necesita el usuario final:`n$List"
    }
}

function Assert-RequiredReleaseFiles {
    param(
        [string[]]$Files,
        [string[]]$RequiredFiles
    )

    $Missing = @()
    foreach ($Required in $RequiredFiles) {
        if ($Files -notcontains $Required) {
            $Missing += $Required
        }
    }
    if ($Missing.Count -gt 0) {
        throw "Faltan archivos obligatorios del paquete:`n$($Missing -join "`n")"
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

if (Test-Path -LiteralPath (Join-Path $Root "crear_launcher_windows.ps1")) {
    Write-Step "Actualizando lanzador de Windows"
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "crear_launcher_windows.ps1")
    } catch {
        Write-Host "Aviso: no se pudo crear Corrector CARM.exe. El paquete mantendra los lanzadores .cmd. Detalle: $_" -ForegroundColor Yellow
    }
}

Write-Step "Creando paquete guiado"
New-Item -ItemType Directory -Path $PackageDir | Out-Null

$ReleaseFiles = @(
    ".env.example",
    "VERSION",
    "INSTRUCCIONES_CODEX_PERSONALIZADAS.md",
    "requirements.txt",
    "requirements-extraccion.txt",
    "prompts_correccion.json",
    "corrector_agente.py",
    "interfaz_app.py",
    "verificar_app.py",
    "verificar_app_windows.cmd",
    "verificar_app_windows.ps1",
    "INSTALAR_CORRECTOR_CARM.cmd",
    "instalador_guiado_windows.cmd",
    "instalador_guiado_windows.ps1",
    "ABRIR_CORRECTOR_CARM.cmd",
    "instalar_windows.cmd",
    "instalar_windows.ps1",
    "iniciar_app_windows.cmd",
    "iniciar_app_windows.ps1",
    "reparar_dependencias_windows.cmd",
    "reparar_dependencias_windows.ps1",
    "instalar_ocr_windows.cmd",
    "instalar_ocr_windows.ps1",
    "desinstalar_windows.cmd",
    "desinstalar_windows.ps1",
    "crear_launcher_windows.cmd",
    "crear_launcher_windows.ps1",
    "Corrector CARM.exe",
    "assets/corrector_carm.ico",
    "assets/corrector_carm.png"
)

$RequiredReleaseFiles = @(
    ".env.example",
    "requirements.txt",
    "corrector_agente.py",
    "interfaz_app.py",
    "INSTALAR_CORRECTOR_CARM.cmd",
    "instalador_guiado_windows.ps1",
    "instalar_windows.ps1",
    "iniciar_app_windows.ps1",
    "ABRIR_CORRECTOR_CARM.cmd",
    "desinstalar_windows.ps1",
    "verificar_app.py"
)

$Files = @($ReleaseFiles) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Sort-Object -Unique

Assert-RequiredReleaseFiles -Files $Files -RequiredFiles $RequiredReleaseFiles

foreach ($File in $Files) {
    Copy-ReleaseFile -RelativePath $File -DestinationRoot $PackageDir
}

$Readme = @"
Corrector CARM $Version

Para usuarios:
- Usa INSTALAR_CORRECTOR_CARM.cmd para instalar.
- Usa ABRIR_CORRECTOR_CARM.cmd o el acceso directo de Windows para abrir la interfaz.
- Usa GUIA_USUARIO.txt para el primer uso.
- Usa desinstalar_windows.cmd solo si quieres quitar la app manualmente o no aparece en Aplicaciones instaladas.

Instalacion guiada en otro Windows:
1. Descomprime esta carpeta.
2. Haz doble clic en INSTALAR_CORRECTOR_CARM.cmd.
3. Revisa la comprobacion previa: Python, dependencias, OCR opcional, Node.js/npm/Codex y carpetas existentes.
4. Elige carpeta de instalacion, carpeta de datos, acceso directo e inicio con Windows.
5. Si eliges carpetas existentes, el instalador actualiza la app y reutiliza datos/configuracion compatibles.
6. El instalador copia la app a su sitio, prepara dependencias y crea accesos directos.
7. Abre Corrector CARM desde el Escritorio, menu Inicio o el lanzador.
8. La primera vez, configura credenciales CARM desde la interfaz si faltan.
9. Si vas a corregir sin API con Codex, inicia sesion una vez con ChatGPT ejecutando: codex login.

Entradas utiles:
- Corrector CARM.exe: lanzador visual de Windows con icono propio.
- INSTALAR_CORRECTOR_CARM.cmd: instalacion guiada recomendada.
- instalador_guiado_windows.cmd: asistente visual de instalacion.
- ABRIR_CORRECTOR_CARM.cmd: abre el panel de la app.
- desinstalar_windows.cmd: desinstalacion local si no aparece en Aplicaciones instaladas.
- verificar_app_windows.cmd: diagnostico local.

Archivos de mantenimiento:
- instalar_windows.*: instalador tecnico usado por el asistente.
- iniciar_app_windows.*: arranque interno de la app y bandeja.
- reparar_dependencias_windows.*: repara dependencias, Chromium y entorno local.
- instalar_ocr_windows.*: instala OCR opcional para PDF escaneados.
- verificar_app.*: diagnostico de instalacion local.

Notas:
- No incluye .env real, cache, logs, entregas ni correcciones generadas.
- No incluye roadmap, estado interno, AGENTS ni checklist de desarrollo.
- La app escucha solo en 127.0.0.1.
- La subida a CARM es asistida: el docente revisa y guarda manualmente.
"@
Set-Content -LiteralPath (Join-Path $PackageDir "LEEME_INSTALACION.txt") -Value $Readme -Encoding UTF8

$UserGuide = @"
Corrector CARM - Guia de usuario

Primer uso:
1. Ejecuta INSTALAR_CORRECTOR_CARM.cmd.
2. Abre Corrector CARM desde el acceso directo o ABRIR_CORRECTOR_CARM.cmd.
3. Entra en Configuracion y guarda tus credenciales CARM.
4. Pulsa detectar cursos y selecciona el curso o cursos que quieras preparar.
5. Usa preparar prompts para dejar listas las entregas pendientes.

Modos de correccion:
- Con OpenAI API: guarda la API key desde Configuracion y pulsa corregir prompts con API cuando quieras gastar API.
- Sin API: usa los prompts de pendientes/prompts_codex con Codex u otra IA, genera los *_correccion.json y despues importalos desde la interfaz.
- Si marcas la opcion de Codex en el instalador, intentara detectar Node.js/npm, instalar Node.js LTS con winget si falta e instalar el CLI oficial con npm.
- Tras instalar Codex CLI, inicia sesion una vez con ChatGPT ejecutando: codex login. La app puede instalar el CLI, pero no puede iniciar sesion por ti.
- El proyecto local de Codex por curso incluye un indice, enunciados y unidades completas en codex_project\unidades, sin entregas ni datos personales.

Subida a CARM:
- La app usa subida asistida.
- Revisa nota y feedback antes de guardar.
- El docente pulsa Guardar cambios en CARM.
- La app solo retira filas pendientes cuando se confirma el guardado.

Reparacion:
- Si falta Playwright, Chromium o dependencias, ejecuta reparar_dependencias_windows.cmd.
- Si quieres OCR para PDF escaneados, ejecuta instalar_ocr_windows.cmd o marca OCR en el instalador.
- Si necesitas diagnostico, ejecuta verificar_app_windows.cmd.

Desinstalacion:
- Preferente: Configuracion de Windows > Aplicaciones instaladas > Corrector CARM.
- Alternativa: desinstalar_windows.cmd.
- Por defecto conserva datos locales.
- En modo grafico puedes elegir borrar pendientes/prompts, CSV temporales o cursos/cache/proyectos Codex.
- Para borrar todo desde consola: desinstalar_windows.ps1 -EliminarDatos.
- Para borrar solo una parte desde consola: usa -EliminarPendientes, -EliminarTemporal o -EliminarCursos.

Privacidad y seguridad:
- El paquete no incluye credenciales, .env real, cache, logs, entregas ni correcciones.
- La interfaz local escucha solo en 127.0.0.1.
- La publicacion directa queda bloqueada; el flujo normal requiere revision humana.
- No compartas carpetas de datos si contienen entregas, notas, logs o correcciones.
"@
Set-Content -LiteralPath (Join-Path $PackageDir "GUIA_USUARIO.txt") -Value $UserGuide -Encoding UTF8

$Manifest = [ordered]@{
    nombre = $PackageName
    version = $Version
    creado = (Get-Date).ToString("s")
    origen = $Root
    instalador_principal = "INSTALAR_CORRECTOR_CARM.cmd"
    lanzador_panel = "ABRIR_CORRECTOR_CARM.cmd"
    lanzador_windows = "Corrector CARM.exe"
    tipo = "paquete_usuario_final"
    incluye_secretos = $false
    incluye_archivos_desarrollo = $false
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
