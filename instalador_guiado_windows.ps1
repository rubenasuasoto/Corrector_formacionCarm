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
$InstallerLogPath = Join-Path $env:TEMP "Corrector_CARM_instalador.log"

function Write-InstallerLog([string]$Message) {
    try {
        $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        Add-Content -LiteralPath $InstallerLogPath -Encoding UTF8 -Value "$stamp $Message"
    } catch {}
}

function Show-InstallerError([string]$Message) {
    Write-InstallerLog "[ERROR] $Message"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "$Message`n`nRevisa el log del instalador:`n$InstallerLogPath",
            "Instalador Corrector CARM",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } catch {
        Write-Host $Message -ForegroundColor Red
        Write-Host "Log: $InstallerLogPath" -ForegroundColor Yellow
    }
}

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
    Write-InstallerLog "==> $Message"
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

function Quote-PowerShellLiteral([string]$Value) {
    return "'" + ($Value -replace "'", "''") + "'"
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

function Get-InstalledAppLocation {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Corrector CARM"
    try {
        if (Test-Path -LiteralPath $key) {
            $props = Get-ItemProperty -LiteralPath $key -ErrorAction Stop
            if ($props.InstallLocation) {
                return [IO.Path]::GetFullPath([string]$props.InstallLocation)
            }
        }
    } catch {}
    return ""
}

function Backup-PreviousInstallState([string]$Root) {
    $backup = Join-Path $env:TEMP ("Corrector_CARM_backup_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    foreach ($name in @(".env", ".corrector_app.json")) {
        $source = Join-Path $Root $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $backup $name) -Force
        }
    }
    return $backup
}

function Restore-PreviousInstallState([string]$Root, [string]$BackupRoot) {
    if (-not $BackupRoot -or -not (Test-Path -LiteralPath $BackupRoot)) {
        return
    }
    foreach ($name in @(".env", ".corrector_app.json")) {
        $source = Join-Path $BackupRoot $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $Root $name) -Force
        }
    }
    Remove-Item -LiteralPath $BackupRoot -Force -Recurse -ErrorAction SilentlyContinue
}

function Invoke-PreviousInstallCleanup([string]$TargetRoot) {
    $targetFull = Resolve-FullPath $TargetRoot
    $sourceFull = Resolve-FullPath $SourceRoot
    if (-not $targetFull -or -not (Test-Path -LiteralPath $targetFull)) {
        return ""
    }
    if ($targetFull.TrimEnd("\") -ieq $sourceFull.TrimEnd("\")) {
        Write-InstallerLog "Se omite limpieza previa porque la ruta de instalacion coincide con el codigo fuente."
        return ""
    }
    if ((Test-Path -LiteralPath (Join-Path $targetFull ".git"))) {
        Write-InstallerLog "Se omite limpieza previa porque la ruta parece un repositorio Git: $targetFull"
        return ""
    }
    if ($targetFull -notmatch "Corrector CARM") {
        Write-InstallerLog "Se omite limpieza previa por seguridad; ruta no reconocida como instalacion Corrector CARM: $targetFull"
        return ""
    }

    Write-Step "Desinstalando version anterior"
    $backup = Backup-PreviousInstallState $targetFull
    $oldUninstaller = Join-Path $targetFull "desinstalar_windows.ps1"
    if (Test-Path -LiteralPath $oldUninstaller) {
        $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Quote-Arg $oldUninstaller), "-Silencioso")
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList ($args -join " ") -WorkingDirectory $targetFull -Wait -PassThru -WindowStyle Hidden
        if ($proc.ExitCode -ne 0) {
            throw "La desinstalacion de la version anterior fallo con codigo $($proc.ExitCode)."
        }
    } else {
        Write-InstallerLog "No se encontro desinstalador anterior; se elimina carpeta de app conservando copia de configuracion."
        Remove-Item -LiteralPath $targetFull -Force -Recurse -ErrorAction Stop
    }
    return $backup
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
    $json = $config | ConvertTo-Json -Depth 4
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $Root ".corrector_app.json"), $json, $utf8NoBom)
}

function Invoke-ProcessWithProgress {
    param(
        [string]$Title,
        [string]$Message,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = $Title
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ControlBox = $false
    $form.ClientSize = New-Object System.Drawing.Size(820, 520)
    $iconPath = Join-Path $SourceRoot "assets\corrector_carm.ico"
    if (Test-Path -LiteralPath $iconPath) {
        try { $form.Icon = New-Object System.Drawing.Icon($iconPath) } catch {}
    }

    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.Text = $Message
    $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
    $titleLabel.Location = New-Object System.Drawing.Point(24, 22)
    $titleLabel.Size = New-Object System.Drawing.Size(760, 28)
    $form.Controls.Add($titleLabel)

    $detailLabel = New-Object System.Windows.Forms.Label
    $detailLabel.Text = "Puedes dejar esta ventana abierta. El instalador esta trabajando en segundo plano."
    $detailLabel.ForeColor = [System.Drawing.Color]::DimGray
    $detailLabel.Location = New-Object System.Drawing.Point(24, 54)
    $detailLabel.Size = New-Object System.Drawing.Size(760, 24)
    $form.Controls.Add($detailLabel)

    $progress = New-Object System.Windows.Forms.ProgressBar
    $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
    $progress.MarqueeAnimationSpeed = 35
    $progress.Location = New-Object System.Drawing.Point(26, 90)
    $progress.Size = New-Object System.Drawing.Size(768, 18)
    $form.Controls.Add($progress)

    $stepsLabel = New-Object System.Windows.Forms.Label
    $stepsLabel.Text = "Pasos"
    $stepsLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $stepsLabel.Location = New-Object System.Drawing.Point(26, 122)
    $stepsLabel.Size = New-Object System.Drawing.Size(250, 20)
    $form.Controls.Add($stepsLabel)

    $stepsList = New-Object System.Windows.Forms.ListView
    $stepsList.View = [System.Windows.Forms.View]::Details
    $stepsList.FullRowSelect = $true
    $stepsList.HeaderStyle = [System.Windows.Forms.ColumnHeaderStyle]::None
    [void]$stepsList.Columns.Add("Estado", 82)
    [void]$stepsList.Columns.Add("Paso", 190)
    $stepsList.Location = New-Object System.Drawing.Point(26, 146)
    $stepsList.Size = New-Object System.Drawing.Size(286, 300)
    $form.Controls.Add($stepsList)

    $logLabel = New-Object System.Windows.Forms.Label
    $logLabel.Text = "Detalle"
    $logLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $logLabel.Location = New-Object System.Drawing.Point(328, 122)
    $logLabel.Size = New-Object System.Drawing.Size(250, 20)
    $form.Controls.Add($logLabel)

    $logBox = New-Object System.Windows.Forms.TextBox
    $logBox.Multiline = $true
    $logBox.ReadOnly = $true
    $logBox.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
    $logBox.Font = New-Object System.Drawing.Font("Consolas", 8.5)
    $logBox.Location = New-Object System.Drawing.Point(328, 146)
    $logBox.Size = New-Object System.Drawing.Size(466, 300)
    $form.Controls.Add($logBox)
    $logBox.AppendText("Log: $InstallerLogPath" + [Environment]::NewLine)
    Write-InstallerLog "Iniciando fase tecnica: $FilePath $($Arguments -join ' ')"

    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Text = "Cerrar"
    $closeButton.Enabled = $false
    $closeButton.Location = New-Object System.Drawing.Point(704, 466)
    $closeButton.Size = New-Object System.Drawing.Size(90, 28)
    $closeButton.Add_Click({ $form.Close() })
    $form.Controls.Add($closeButton)
    $form.Add_FormClosing({
        param($sender, $eventArgs)
        try {
            if ($process -and -not $process.HasExited -and -not $closeButton.Enabled) {
                $eventArgs.Cancel = $true
                $detailLabel.Text = "La instalacion sigue en curso. Espera a que termine."
            }
        } catch {}
    })

    $stepNames = @(
        "Python",
        "Entorno virtual",
        "Dependencias",
        "Lectura avanzada",
        "OCR",
        "Codex CLI",
        "Chromium",
        "Configuracion local",
        "Lanzador",
        "Verificacion",
        "Arranque Windows",
        "Accesos directos",
        "Desinstalador"
    )
    $stepItems = @{}
    foreach ($stepName in $stepNames) {
        $item = New-Object System.Windows.Forms.ListViewItem("Pendiente")
        [void]$item.SubItems.Add($stepName)
        [void]$stepsList.Items.Add($item)
        $stepItems[$stepName] = $item
    }
    $currentStep = ""
    $setStepStatus = {
        param([string]$Name, [string]$Status)
        if (-not $stepItems.ContainsKey($Name)) { return }
        $item = $stepItems[$Name]
        $item.Text = $Status
        if ($Status -eq "En curso") {
            $item.BackColor = [System.Drawing.Color]::FromArgb(234, 241, 248)
            $item.ForeColor = [System.Drawing.Color]::FromArgb(47, 95, 149)
            $stepsList.EnsureVisible($item.Index)
        } elseif ($Status -eq "OK") {
            $item.BackColor = [System.Drawing.Color]::FromArgb(232, 244, 238)
            $item.ForeColor = [System.Drawing.Color]::FromArgb(31, 122, 91)
        } elseif ($Status -eq "Aviso") {
            $item.BackColor = [System.Drawing.Color]::FromArgb(255, 248, 234)
            $item.ForeColor = [System.Drawing.Color]::FromArgb(168, 98, 0)
        } elseif ($Status -eq "Error") {
            $item.BackColor = [System.Drawing.Color]::FromArgb(255, 241, 240)
            $item.ForeColor = [System.Drawing.Color]::FromArgb(180, 35, 24)
        } else {
            $item.BackColor = [System.Drawing.Color]::White
            $item.ForeColor = [System.Drawing.Color]::DimGray
        }
    }
    $stepForLine = {
        param([string]$Line)
        if ($Line -match "Python") { return "Python" }
        if ($Line -match "entorno virtual|\.venv") { return "Entorno virtual" }
        if ($Line -match "pip|dependencias base") { return "Dependencias" }
        if ($Line -match "opcionales|extraccion") { return "Lectura avanzada" }
        if ($Line -match "OCR|Tesseract") { return "OCR" }
        if ($Line -match "Codex|Node\.js|npm") { return "Codex CLI" }
        if ($Line -match "Chromium|Playwright") { return "Chromium" }
        if ($Line -match "\.env|configuracion local") { return "Configuracion local" }
        if ($Line -match "lanzador") { return "Lanzador" }
        if ($Line -match "Verificando app|Compilacion|Verificando instalacion") { return "Verificacion" }
        if ($Line -match "arranque automatico") { return "Arranque Windows" }
        if ($Line -match "accesos directos") { return "Accesos directos" }
        if ($Line -match "desinstalador") { return "Desinstalador" }
        return ""
    }

    $queue = New-Object 'System.Collections.Concurrent.ConcurrentQueue[string]'
    $stdoutLog = Join-Path $env:TEMP "Corrector_CARM_instalador_stdout.log"
    $stderrLog = Join-Path $env:TEMP "Corrector_CARM_instalador_stderr.log"
    $runnerScript = Join-Path $env:TEMP "Corrector_CARM_instalador_runner.ps1"
    Remove-Item -LiteralPath $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue
    $runnerArgs = ($Arguments | ForEach-Object {
        $arg = [string]$_
        if ($arg.Length -ge 2 -and $arg.StartsWith('"') -and $arg.EndsWith('"')) {
            $arg = $arg.Substring(1, $arg.Length - 2)
        }
        Quote-PowerShellLiteral $arg
    }) -join ",`n"
    $runnerExe = Quote-PowerShellLiteral $FilePath
    $runnerStdout = Quote-PowerShellLiteral $stdoutLog
    $runnerContent = @"
`$ErrorActionPreference = 'Continue'
`$exe = $runnerExe
`$utf8NoBom = New-Object System.Text.UTF8Encoding(`$false)
function Write-RunnerLine([object]`$Value) {
    [System.IO.File]::AppendAllText($runnerStdout, ([string]`$Value + [Environment]::NewLine), `$utf8NoBom)
}
`$argsList = @(
$runnerArgs
)
try {
    & `$exe @argsList 2>&1 | ForEach-Object { Write-RunnerLine `$_ }
    if (`$null -ne `$LASTEXITCODE) { exit `$LASTEXITCODE }
    exit 0
} catch {
    Write-RunnerLine `"ERROR EJECUTANDO INSTALADOR TECNICO: `$(`$_ | Out-String)`"
    exit 1
}
"@
    Set-Content -LiteralPath $runnerScript -Value $runnerContent -Encoding UTF8
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName = "powershell.exe"
    $process.StartInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File " + (Quote-Arg $runnerScript)
    $process.StartInfo.WorkingDirectory = $WorkingDirectory
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $process.StartInfo.RedirectStandardOutput = $false
    $process.StartInfo.RedirectStandardError = $false

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 150
    $exitCode = $null
    $lastStdoutLength = 0
    $lastStderrLength = 0
    $readLogLines = {
        param([string]$Path, [ref]$LastLength)
        if (-not (Test-Path -LiteralPath $Path)) { return }
        try {
            $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            try {
                if ($stream.Length -lt $LastLength.Value) {
                    $LastLength.Value = 0
                }
                if ($stream.Length -le $LastLength.Value) {
                    return
                }
                $stream.Seek($LastLength.Value, [System.IO.SeekOrigin]::Begin) | Out-Null
                $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
                $chunk = $reader.ReadToEnd()
                $LastLength.Value = $stream.Position
                foreach ($part in ($chunk -split "(`r`n|`n|`r)")) {
                    if (-not [string]::IsNullOrWhiteSpace($part)) {
                        $queue.Enqueue($part)
                    }
                }
            } finally {
                $stream.Dispose()
            }
        } catch {
            Write-InstallerLog "[WARN LOG READ] $_"
        }
    }
    $timer.Add_Tick({
        try {
            & $readLogLines $stdoutLog ([ref]$lastStdoutLength)
            & $readLogLines $stderrLog ([ref]$lastStderrLength)
            $line = $null
            while ($queue.TryDequeue([ref]$line)) {
                Write-InstallerLog $line
                $logBox.AppendText($line + [Environment]::NewLine)
                $logBox.SelectionStart = $logBox.TextLength
                $logBox.ScrollToCaret()
                $detectedStep = & $stepForLine $line
                if ($detectedStep) {
                    if ($currentStep -and $currentStep -ne $detectedStep) {
                        & $setStepStatus $currentStep "OK"
                    }
                    $currentStep = $detectedStep
                    & $setStepStatus $currentStep "En curso"
                    $detailLabel.Text = "Ahora: $detectedStep"
                }
                if ($line -match "No se pudo|fallo|ERROR|Error") {
                    if ($currentStep) { & $setStepStatus $currentStep "Aviso" }
                }
                $line = $null
            }
            if ($process.HasExited) {
                $timer.Stop()
                $script:__CorrectorProgressExitCode = $process.ExitCode
                Write-InstallerLog "Fase tecnica terminada con codigo $($process.ExitCode)"
                $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Blocks
                $progress.MarqueeAnimationSpeed = 0
                if ($process.ExitCode -eq 0) {
                    if ($currentStep) { & $setStepStatus $currentStep "OK" }
                    $progress.Value = 100
                    $titleLabel.Text = "Instalacion completada"
                    $detailLabel.Text = "Todo ha terminado correctamente."
                    $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
                    $form.Close()
                } else {
                    if ($currentStep) { & $setStepStatus $currentStep "Error" }
                    $titleLabel.Text = "La instalacion necesita revision"
                    $detailLabel.Text = "Revisa el detalle. El log queda guardado en $InstallerLogPath"
                    $closeButton.Text = "Continuar"
                    $closeButton.Enabled = $true
                    $form.ControlBox = $true
                }
            }
        } catch {
            $timer.Stop()
            $script:__CorrectorProgressExitCode = 1
            Write-InstallerLog "[ERROR UI] $_"
            $titleLabel.Text = "La instalacion necesita revision"
            $detailLabel.Text = "Se produjo un error mostrando el progreso. El log queda guardado en $InstallerLogPath"
            $closeButton.Text = "Continuar"
            $closeButton.Enabled = $true
            $form.ControlBox = $true
        }
    })

    $script:__CorrectorProgressExitCode = $null
    try {
        [void]$process.Start()
        $timer.Start()
        [void]$form.ShowDialog()
    } catch {
        Write-InstallerLog "[ERROR START] $_"
        Show-InstallerError "No se pudo iniciar la fase tecnica de instalacion: $_"
        return 1
    }
    $timer.Stop()
    if ($null -eq $script:__CorrectorProgressExitCode) {
        $script:__CorrectorProgressExitCode = $process.ExitCode
    }
    return [int]$script:__CorrectorProgressExitCode
}

try {
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
$previousInstallLocation = Get-InstalledAppLocation
if ($previousInstallLocation -and $previousInstallLocation.TrimEnd("\") -ine $TargetRoot.TrimEnd("\")) {
    Write-InstallerLog "Version previa registrada en otra ruta: $previousInstallLocation. La nueva instalacion usara: $TargetRoot"
}
$previousBackup = Invoke-PreviousInstallCleanup $TargetRoot
Copy-AppFiles -From $SourceRoot -To $TargetRoot
Restore-PreviousInstallState -Root $TargetRoot -BackupRoot $previousBackup

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
$exitCode = 0
if ($SinInterfaz) {
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList ($installArgs -join " ") -WorkingDirectory $TargetRoot -Wait -PassThru -WindowStyle Hidden
    $exitCode = $proc.ExitCode
} else {
    $exitCode = Invoke-ProcessWithProgress `
        -Title "Instalando Corrector CARM" `
        -Message "Instalando dependencias y preparando la app" `
        -FilePath "powershell.exe" `
        -Arguments $installArgs `
        -WorkingDirectory $TargetRoot
}
if ($exitCode -ne 0) {
    throw "La instalacion tecnica fallo con codigo $exitCode."
}

Write-Step "Confirmando configuracion local"
Write-AppConfig -Root $TargetRoot -DataRoot $TargetData -PrepararCodex ([bool]$choices.PrepararCodex)

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
Write-InstallerLog "Instalacion completada correctamente. Instalacion: $TargetRoot Datos: $TargetData"
} catch {
    Show-InstallerError "La instalacion no se ha completado correctamente: $_"
    exit 1
}
