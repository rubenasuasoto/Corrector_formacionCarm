param(
    [switch]$SinInterfaz,
    [string]$InstallDir,
    [string]$DataDir,
    [switch]$NoAccesoDirecto,
    [switch]$NoInicioWindows,
    [switch]$NoInstalarOCR,
    [switch]$NoPrepararCodex,
    [switch]$NoAbrirAlFinal
)

$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DefaultInstallDir = Join-Path $env:LOCALAPPDATA "Programs\Corrector CARM"
$DefaultDataDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Corrector CARM"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-FullPath([string]$PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    return [IO.Path]::GetFullPath($PathValue)
}

function Quote-Arg([string]$Value) {
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Read-ExistingAppConfig([string]$Root) {
    $configPath = Join-Path $Root ".corrector_app.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-DefaultDataDir {
    if ($DataDir) {
        return $DataDir
    }
    $candidateRoot = $DefaultInstallDir
    if ($InstallDir) {
        $candidateRoot = $InstallDir
    }
    $existing = Read-ExistingAppConfig $candidateRoot
    if ($existing -and $existing.courses_dir) {
        try {
            return Split-Path -Parent ([IO.Path]::GetFullPath([string]$existing.courses_dir))
        } catch {}
    }
    return $DefaultDataDir
}

function Get-CommandSourceSafe([string]$Name) {
    try {
        $cmd = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd -and $cmd.Source) {
            return [string]$cmd.Source
        }
    } catch {}
    return ""
}

function Find-PythonInstallerCommand {
    $fromPath = Get-CommandSourceSafe "py"
    if ($fromPath) { return "py" }
    $fromPath = Get-CommandSourceSafe "python"
    if ($fromPath) { return "python" }
    return ""
}

function Get-PythonInstallerVersion([string]$PythonCommand) {
    if (-not $PythonCommand) { return "" }
    try {
        return (& $PythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    } catch {
        return ""
    }
}

function Test-PythonInstallerVersion([string]$PythonCommand) {
    $versionText = Get-PythonInstallerVersion $PythonCommand
    if (-not $versionText) { return $false }
    $parts = $versionText.Split(".")
    return ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 12))
}

function Find-WingetInstallerCommand {
    return Get-CommandSourceSafe "winget.exe"
}

function Find-NodeInstallerCommand {
    $fromPath = Get-CommandSourceSafe "node.exe"
    if ($fromPath) { return $fromPath }
    $programFiles = Join-Path $env:ProgramFiles "nodejs\node.exe"
    if (Test-Path -LiteralPath $programFiles) { return $programFiles }
    return ""
}

function Find-NpmInstallerCommand {
    $fromPath = Get-CommandSourceSafe "npm.cmd"
    if ($fromPath) { return $fromPath }
    $programFiles = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
    if (Test-Path -LiteralPath $programFiles) { return $programFiles }
    return ""
}

function Find-CodexInstallerCommand {
    $npmCodex = Join-Path $env:APPDATA "npm\codex.cmd"
    $candidates = @(
        $npmCodex,
        (Get-CommandSourceSafe "codex.cmd"),
        (Get-CommandSourceSafe "codex")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate) -and $candidate -notmatch "\\.vscode\\extensions\\openai\.chatgpt-" -and $candidate -notmatch "\.ps1$") {
            return $candidate
        }
    }
    return ""
}

function Get-InstallerDependencyReport {
    param(
        [string]$InstallPath,
        [string]$DataPath,
        [bool]$InstallOcr,
        [bool]$PrepareCodex
    )

    $lines = New-Object System.Collections.Generic.List[string]

    $winget = Find-WingetInstallerCommand
    $python = Find-PythonInstallerCommand
    if ($python -and (Test-PythonInstallerVersion $python)) {
        $versionText = Get-PythonInstallerVersion $python
        $lines.Add("[OK] Python detectado: $versionText ($python)")
    } elseif ($python) {
        $versionText = Get-PythonInstallerVersion $python
        if (-not $versionText) { $versionText = "version no detectable" }
        if ($winget) {
            $lines.Add("[PENDIENTE] Python detectado pero no cumple 3.12+: $versionText. El instalador intentara preparar Python 3.12 con winget.")
        } else {
            $lines.Add("[NECESARIO] Python 3.12+ requerido. Detectado: $versionText. winget no esta disponible; instalalo manualmente antes de continuar.")
        }
    } elseif ($winget) {
        $lines.Add("[PENDIENTE] Python 3.12+ no detectado. El instalador intentara instalarlo con winget.")
    } else {
        $lines.Add("[NECESARIO] Python 3.12+ no detectado y winget no esta disponible. Instala Python 3.12+ manualmente antes de continuar.")
    }

    $lines.Add("[OK] Playwright y Chromium se verificaran/instalaran automaticamente.")
    $lines.Add("[OK] Dependencias Python de la app se instalaran en .venv.")

    if ($InstallOcr) {
        $lines.Add("[OPCIONAL] OCR activado: se intentara preparar lectura de PDF escaneados e imagenes.")
    } else {
        $lines.Add("[OPCIONAL] OCR desactivado: esos archivos quedaran para revision manual.")
    }

    if (Test-Path -LiteralPath $InstallPath) {
        $lines.Add("[INFO] Instalacion existente detectada: se actualizara sin borrar .env ni datos.")
    } else {
        $lines.Add("[INFO] Instalacion nueva: se creara la carpeta de la app.")
    }

    if (Test-Path -LiteralPath $DataPath) {
        $lines.Add("[INFO] Carpeta de datos existente: se reutilizaran cursos, pendientes y temporales.")
    } else {
        $lines.Add("[INFO] Carpeta de datos nueva: se creara al instalar.")
    }

    if ($PrepareCodex) {
        $node = Find-NodeInstallerCommand
        $npm = Find-NpmInstallerCommand
        $codex = Find-CodexInstallerCommand
        if ($node) {
            $lines.Add("[OK] Node.js detectado: $node")
        } else {
            $lines.Add("[PENDIENTE] Node.js no detectado. El instalador intentara instalar Node.js LTS con winget.")
        }
        if ($npm) {
            $lines.Add("[OK] npm detectado: $npm")
        } else {
            $lines.Add("[PENDIENTE] npm no detectado. Se instalara junto a Node.js.")
        }
        if ($codex) {
            $lines.Add("[OK] Codex CLI detectado: $codex")
            try {
                $status = (& $codex login status 2>&1 | Out-String).Trim()
                if ($LASTEXITCODE -eq 0 -and $status -match "Logged in|authenticated|ChatGPT") {
                    $lines.Add("[OK] Codex tiene sesion iniciada.")
                } else {
                    $lines.Add("[ACCION] Codex esta instalado, pero debes iniciar sesion: abre una terminal y ejecuta codex login.")
                }
            } catch {
                $lines.Add("[ACCION] Codex esta instalado, pero no se pudo comprobar la sesion. Ejecuta codex login si el modo sin API falla.")
            }
        } else {
            $lines.Add("[PENDIENTE] Codex CLI no detectado. El instalador intentara instalar @openai/codex.")
            $lines.Add("[ACCION] Tras instalar, inicia sesion con ChatGPT ejecutando codex login.")
        }
    } else {
        $lines.Add("[INFO] Integracion Codex desactivada. Podras usar API o prompts manuales.")
    }

    $lines.Add("")
    $lines.Add("Importante: para corregir sin API necesitas iniciar sesion en Codex con tu cuenta de ChatGPT. La app puede instalar el CLI, pero no puede iniciar sesion por ti.")
    return ($lines -join [Environment]::NewLine)
}

function Show-InstallerForm {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Instalador Corrector CARM"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ClientSize = New-Object System.Drawing.Size(780, 620)
    $iconPath = Join-Path $SourceRoot "assets\corrector_carm.ico"
    if (Test-Path -LiteralPath $iconPath) {
        try { $form.Icon = New-Object System.Drawing.Icon($iconPath) } catch {}
    }

    $picturePath = Join-Path $SourceRoot "assets\corrector_carm.png"
    if (Test-Path -LiteralPath $picturePath) {
        $picture = New-Object System.Windows.Forms.PictureBox
        $picture.Image = [System.Drawing.Image]::FromFile($picturePath)
        $picture.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
        $picture.Location = New-Object System.Drawing.Point(24, 18)
        $picture.Size = New-Object System.Drawing.Size(48, 48)
        $form.Controls.Add($picture)
    }

    $title = New-Object System.Windows.Forms.Label
    $title.Text = "Corrector CARM"
    $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
    $title.Location = New-Object System.Drawing.Point(86, 18)
    $title.Size = New-Object System.Drawing.Size(650, 32)
    $form.Controls.Add($title)

    $subtitle = New-Object System.Windows.Forms.Label
    $subtitle.Text = "Configura la instalacion local. El asistente detecta dependencias y prepara lo necesario."
    $subtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $subtitle.Location = New-Object System.Drawing.Point(88, 55)
    $subtitle.Size = New-Object System.Drawing.Size(650, 24)
    $form.Controls.Add($subtitle)

    $installLabel = New-Object System.Windows.Forms.Label
    $installLabel.Text = "Carpeta de instalacion"
    $installLabel.Location = New-Object System.Drawing.Point(28, 92)
    $installLabel.Size = New-Object System.Drawing.Size(220, 20)
    $form.Controls.Add($installLabel)

    $installBox = New-Object System.Windows.Forms.TextBox
    $installBox.Text = if ($InstallDir) { $InstallDir } else { $DefaultInstallDir }
    $installBox.Location = New-Object System.Drawing.Point(30, 116)
    $installBox.Size = New-Object System.Drawing.Size(610, 24)
    $form.Controls.Add($installBox)

    $installBrowse = New-Object System.Windows.Forms.Button
    $installBrowse.Text = "Elegir..."
    $installBrowse.Location = New-Object System.Drawing.Point(650, 114)
    $installBrowse.Size = New-Object System.Drawing.Size(88, 28)
    $form.Controls.Add($installBrowse)

    $dataLabel = New-Object System.Windows.Forms.Label
    $dataLabel.Text = "Carpeta de datos, descargas, prompts y CSV"
    $dataLabel.Location = New-Object System.Drawing.Point(28, 152)
    $dataLabel.Size = New-Object System.Drawing.Size(320, 20)
    $form.Controls.Add($dataLabel)

    $dataBox = New-Object System.Windows.Forms.TextBox
    $dataBox.Text = Get-DefaultDataDir
    $dataBox.Location = New-Object System.Drawing.Point(30, 176)
    $dataBox.Size = New-Object System.Drawing.Size(610, 24)
    $form.Controls.Add($dataBox)

    $dataBrowse = New-Object System.Windows.Forms.Button
    $dataBrowse.Text = "Elegir..."
    $dataBrowse.Location = New-Object System.Drawing.Point(650, 174)
    $dataBrowse.Size = New-Object System.Drawing.Size(88, 28)
    $form.Controls.Add($dataBrowse)

    $shortcutCheck = New-Object System.Windows.Forms.CheckBox
    $shortcutCheck.Text = "Crear acceso directo en Escritorio y menu Inicio"
    $shortcutCheck.Checked = -not $NoAccesoDirecto
    $shortcutCheck.Location = New-Object System.Drawing.Point(32, 220)
    $shortcutCheck.Size = New-Object System.Drawing.Size(420, 24)
    $form.Controls.Add($shortcutCheck)

    $startupCheck = New-Object System.Windows.Forms.CheckBox
    $startupCheck.Text = "Iniciar Corrector CARM al encender Windows"
    $startupCheck.Checked = -not $NoInicioWindows
    $startupCheck.Location = New-Object System.Drawing.Point(32, 248)
    $startupCheck.Size = New-Object System.Drawing.Size(420, 24)
    $form.Controls.Add($startupCheck)

    $ocrCheck = New-Object System.Windows.Forms.CheckBox
    $ocrCheck.Text = "Instalar OCR para leer PDF escaneados e imagenes"
    $ocrCheck.Checked = -not $NoInstalarOCR
    $ocrCheck.Location = New-Object System.Drawing.Point(32, 276)
    $ocrCheck.Size = New-Object System.Drawing.Size(470, 24)
    $form.Controls.Add($ocrCheck)

    $codexCheck = New-Object System.Windows.Forms.CheckBox
    $codexCheck.Text = "Instalar/preparar Node.js y Codex CLI sin API"
    $codexCheck.Checked = -not $NoPrepararCodex
    $codexCheck.Location = New-Object System.Drawing.Point(32, 304)
    $codexCheck.Size = New-Object System.Drawing.Size(470, 24)
    $form.Controls.Add($codexCheck)

    $openCheck = New-Object System.Windows.Forms.CheckBox
    $openCheck.Text = "Abrir la app al terminar"
    $openCheck.Checked = -not $NoAbrirAlFinal
    $openCheck.Location = New-Object System.Drawing.Point(32, 332)
    $openCheck.Size = New-Object System.Drawing.Size(420, 24)
    $form.Controls.Add($openCheck)

    $hint = New-Object System.Windows.Forms.Label
    $hint.Text = "Si eliges carpetas existentes, el instalador actualiza la app y reutiliza datos/configuracion compatibles. Para el modo sin API, inicia sesion en Codex despues de instalar."
    $hint.ForeColor = [System.Drawing.Color]::DimGray
    $hint.Location = New-Object System.Drawing.Point(30, 364)
    $hint.Size = New-Object System.Drawing.Size(710, 36)
    $form.Controls.Add($hint)

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Text = "Comprobacion previa"
    $statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $statusLabel.Location = New-Object System.Drawing.Point(30, 406)
    $statusLabel.Size = New-Object System.Drawing.Size(300, 20)
    $form.Controls.Add($statusLabel)

    $refresh = New-Object System.Windows.Forms.Button
    $refresh.Text = "Actualizar comprobacion"
    $refresh.Location = New-Object System.Drawing.Point(565, 402)
    $refresh.Size = New-Object System.Drawing.Size(175, 28)
    $form.Controls.Add($refresh)

    $statusBox = New-Object System.Windows.Forms.TextBox
    $statusBox.Multiline = $true
    $statusBox.ReadOnly = $true
    $statusBox.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
    $statusBox.Font = New-Object System.Drawing.Font("Consolas", 8.5)
    $statusBox.Location = New-Object System.Drawing.Point(30, 434)
    $statusBox.Size = New-Object System.Drawing.Size(710, 120)
    $form.Controls.Add($statusBox)

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "Cancelar"
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $cancel.Location = New-Object System.Drawing.Point(550, 576)
    $cancel.Size = New-Object System.Drawing.Size(90, 30)
    $form.Controls.Add($cancel)

    $install = New-Object System.Windows.Forms.Button
    $install.Text = "Instalar"
    $install.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $install.Location = New-Object System.Drawing.Point(650, 576)
    $install.Size = New-Object System.Drawing.Size(90, 30)
    $form.Controls.Add($install)
    $form.AcceptButton = $install
    $form.CancelButton = $cancel

    $folderDialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $installBrowse.Add_Click({
        $folderDialog.Description = "Elige donde instalar Corrector CARM"
        $folderDialog.SelectedPath = $installBox.Text
        if ($folderDialog.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
            $installBox.Text = $folderDialog.SelectedPath
            & $updateStatus
        }
    })
    $dataBrowse.Add_Click({
        $folderDialog.Description = "Elige donde guardar datos y descargas"
        $folderDialog.SelectedPath = $dataBox.Text
        if ($folderDialog.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
            $dataBox.Text = $folderDialog.SelectedPath
            & $updateStatus
        }
    })
    $updateStatus = {
        $installFull = $installBox.Text
        $dataFull = $dataBox.Text
        try { $installFull = Resolve-FullPath $installBox.Text } catch {}
        try { $dataFull = Resolve-FullPath $dataBox.Text } catch {}
        $statusBox.Text = Get-InstallerDependencyReport -InstallPath $installFull -DataPath $dataFull -InstallOcr $ocrCheck.Checked -PrepareCodex $codexCheck.Checked
    }
    $refresh.Add_Click($updateStatus)
    $ocrCheck.Add_CheckedChanged($updateStatus)
    $codexCheck.Add_CheckedChanged($updateStatus)
    & $updateStatus

    $result = $form.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    return [ordered]@{
        InstallDir = $installBox.Text
        DataDir = $dataBox.Text
        CrearAccesoDirecto = $shortcutCheck.Checked
        InstalarArranque = $startupCheck.Checked
        InstalarOCR = $ocrCheck.Checked
        PrepararCodex = $codexCheck.Checked
        AbrirAlFinal = $openCheck.Checked
    }
}

function Copy-AppFiles {
    param(
        [string]$From,
        [string]$To
    )

    $fromFull = Resolve-FullPath $From
    $toFull = Resolve-FullPath $To
    if ($fromFull.TrimEnd("\") -ieq $toFull.TrimEnd("\")) {
        return
    }

    New-Item -ItemType Directory -Path $toFull -Force | Out-Null
    $excludedDirs = @(".git", ".venv", "venv", "__pycache__", "logs_correcciones", "respuestas_extraidas", "correcciones_validadas", "cache_carm")
    $excludedFiles = @(".env", ".corrector_app.json")

    Get-ChildItem -LiteralPath $fromFull -Force | ForEach-Object {
        if ($_.PSIsContainer -and $excludedDirs -contains $_.Name) {
            return
        }
        if (-not $_.PSIsContainer -and $excludedFiles -contains $_.Name) {
            return
        }
        $dest = Join-Path $toFull $_.Name
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
    }
}

function Write-AppConfig {
    param([string]$Root, [string]$DataRoot, [bool]$PrepararCodex)

    $pendientes = Join-Path $DataRoot "pendientes"
    $temporal = Join-Path $DataRoot "temporal"
    $cursos = Join-Path $DataRoot "cursos"

    New-Item -ItemType Directory -Path $pendientes -Force | Out-Null
    New-Item -ItemType Directory -Path $temporal -Force | Out-Null
    New-Item -ItemType Directory -Path $cursos -Force | Out-Null

    $existing = Read-ExistingAppConfig $Root
    $config = [ordered]@{}
    if ($existing) {
        $existing.PSObject.Properties | ForEach-Object {
            $config[$_.Name] = $_.Value
        }
    }
    $config["pendientes_dir"] = $pendientes
    $config["temporal_dir"] = $temporal
    $config["courses_dir"] = $cursos
    $config["course_scoped_dirs"] = $true
    if (-not $config.Contains("auto_scan_interval_minutes")) {
        $config["auto_scan_interval_minutes"] = 60
    }
    if (-not $config.Contains("periodic_auto_prepare")) {
        $config["periodic_auto_prepare"] = $false
    }
    if (-not $config.Contains("auto_prepare_interval_minutes")) {
        $config["auto_prepare_interval_minutes"] = 0
    }
    $config["codex_integration_enabled"] = $PrepararCodex
    $config["installer_configured_at"] = (Get-Date).ToString("s")
    $config["installer_reused_existing_data"] = [bool]$existing
    <#
    Estructura resultante:
    $config = [ordered]@{
        pendientes_dir = $pendientes
        temporal_dir = $temporal
        courses_dir = $cursos
        course_scoped_dirs = $true
        auto_scan_interval_minutes = 60
        periodic_auto_prepare = $false
        auto_prepare_interval_minutes = 0
        codex_integration_enabled = $PrepararCodex
        installer_configured_at = (Get-Date).ToString("s")
    }
    #>
    $config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Root ".corrector_app.json") -Encoding UTF8
}

if ($SinInterfaz) {
    $choices = [ordered]@{
        InstallDir = if ($InstallDir) { $InstallDir } else { $DefaultInstallDir }
        DataDir = if ($DataDir) { $DataDir } else { $DefaultDataDir }
        CrearAccesoDirecto = -not $NoAccesoDirecto
        InstalarArranque = -not $NoInicioWindows
        InstalarOCR = -not $NoInstalarOCR
        PrepararCodex = -not $NoPrepararCodex
        AbrirAlFinal = -not $NoAbrirAlFinal
    }
} else {
    $choices = Show-InstallerForm
    if ($null -eq $choices) {
        Write-Host "Instalacion cancelada por el usuario." -ForegroundColor Yellow
        exit 0
    }
}

$TargetRoot = Resolve-FullPath $choices.InstallDir
$TargetData = Resolve-FullPath $choices.DataDir
if (-not $TargetRoot -or -not $TargetData) {
    throw "Debes indicar carpeta de instalacion y carpeta de datos."
}

Write-Step "Copiando app a la carpeta de instalacion"
if (Test-Path -LiteralPath $TargetRoot) {
    Write-Host "Carpeta de instalacion existente detectada; se actualizaran archivos de la app sin borrar .env ni datos locales." -ForegroundColor Yellow
}
Copy-AppFiles -From $SourceRoot -To $TargetRoot

Write-Step "Preparando carpetas de datos"
if (Test-Path -LiteralPath $TargetData) {
    Write-Host "Carpeta de datos existente detectada; se reutilizaran pendientes, temporal y cursos si ya existen." -ForegroundColor Yellow
}
Write-AppConfig -Root $TargetRoot -DataRoot $TargetData -PrepararCodex ([bool]$choices.PrepararCodex)

$installScript = Join-Path $TargetRoot "instalar_windows.ps1"
if (-not (Test-Path -LiteralPath $installScript)) {
    throw "No se encontro instalar_windows.ps1 en $TargetRoot"
}

$installArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Quote-Arg $installScript), "-ConExtraccion")
if ($choices.CrearAccesoDirecto) {
    $installArgs += "-CrearAccesoDirecto"
}
if ($choices.InstalarArranque) {
    $installArgs += "-InstalarArranque"
}
if ($choices.InstalarOCR) {
    $installArgs += "-InstalarOCR"
}
if ($choices.PrepararCodex) {
    $installArgs += "-PrepararCodex"
}

Write-Step "Instalando dependencias y accesos"
$proc = Start-Process -FilePath "powershell.exe" -ArgumentList ($installArgs -join " ") -WorkingDirectory $TargetRoot -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    throw "La instalacion tecnica fallo con codigo $($proc.ExitCode)."
}

if ($choices.AbrirAlFinal) {
    $launcher = Join-Path $TargetRoot "Corrector CARM.exe"
    if (Test-Path -LiteralPath $launcher) {
        Start-Process -FilePath $launcher -WorkingDirectory $TargetRoot
    } else {
        Start-Process -FilePath (Join-Path $TargetRoot "ABRIR_CORRECTOR_CARM.cmd") -WorkingDirectory $TargetRoot
    }
}

Write-Host ""
Write-Host "Corrector CARM instalado correctamente." -ForegroundColor Green
Write-Host "Instalacion: $TargetRoot"
Write-Host "Datos:       $TargetData"
