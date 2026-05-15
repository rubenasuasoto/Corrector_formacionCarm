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

function Show-InstallerForm {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Instalador Corrector CARM"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ClientSize = New-Object System.Drawing.Size(640, 452)

    $title = New-Object System.Windows.Forms.Label
    $title.Text = "Corrector CARM"
    $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
    $title.Location = New-Object System.Drawing.Point(24, 18)
    $title.Size = New-Object System.Drawing.Size(580, 32)
    $form.Controls.Add($title)

    $subtitle = New-Object System.Windows.Forms.Label
    $subtitle.Text = "Configura la instalacion local de la app antes de preparar dependencias."
    $subtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $subtitle.Location = New-Object System.Drawing.Point(26, 55)
    $subtitle.Size = New-Object System.Drawing.Size(580, 24)
    $form.Controls.Add($subtitle)

    $installLabel = New-Object System.Windows.Forms.Label
    $installLabel.Text = "Carpeta de instalacion"
    $installLabel.Location = New-Object System.Drawing.Point(28, 96)
    $installLabel.Size = New-Object System.Drawing.Size(220, 20)
    $form.Controls.Add($installLabel)

    $installBox = New-Object System.Windows.Forms.TextBox
    $installBox.Text = if ($InstallDir) { $InstallDir } else { $DefaultInstallDir }
    $installBox.Location = New-Object System.Drawing.Point(30, 120)
    $installBox.Size = New-Object System.Drawing.Size(480, 24)
    $form.Controls.Add($installBox)

    $installBrowse = New-Object System.Windows.Forms.Button
    $installBrowse.Text = "Elegir..."
    $installBrowse.Location = New-Object System.Drawing.Point(520, 118)
    $installBrowse.Size = New-Object System.Drawing.Size(88, 28)
    $form.Controls.Add($installBrowse)

    $dataLabel = New-Object System.Windows.Forms.Label
    $dataLabel.Text = "Carpeta de datos, descargas, prompts y CSV"
    $dataLabel.Location = New-Object System.Drawing.Point(28, 160)
    $dataLabel.Size = New-Object System.Drawing.Size(320, 20)
    $form.Controls.Add($dataLabel)

    $dataBox = New-Object System.Windows.Forms.TextBox
    $dataBox.Text = if ($DataDir) { $DataDir } else { $DefaultDataDir }
    $dataBox.Location = New-Object System.Drawing.Point(30, 184)
    $dataBox.Size = New-Object System.Drawing.Size(480, 24)
    $form.Controls.Add($dataBox)

    $dataBrowse = New-Object System.Windows.Forms.Button
    $dataBrowse.Text = "Elegir..."
    $dataBrowse.Location = New-Object System.Drawing.Point(520, 182)
    $dataBrowse.Size = New-Object System.Drawing.Size(88, 28)
    $form.Controls.Add($dataBrowse)

    $shortcutCheck = New-Object System.Windows.Forms.CheckBox
    $shortcutCheck.Text = "Crear acceso directo en Escritorio y menu Inicio"
    $shortcutCheck.Checked = -not $NoAccesoDirecto
    $shortcutCheck.Location = New-Object System.Drawing.Point(32, 232)
    $shortcutCheck.Size = New-Object System.Drawing.Size(420, 24)
    $form.Controls.Add($shortcutCheck)

    $startupCheck = New-Object System.Windows.Forms.CheckBox
    $startupCheck.Text = "Iniciar Corrector CARM al encender Windows"
    $startupCheck.Checked = -not $NoInicioWindows
    $startupCheck.Location = New-Object System.Drawing.Point(32, 260)
    $startupCheck.Size = New-Object System.Drawing.Size(420, 24)
    $form.Controls.Add($startupCheck)

    $ocrCheck = New-Object System.Windows.Forms.CheckBox
    $ocrCheck.Text = "Instalar OCR para leer PDF escaneados e imagenes"
    $ocrCheck.Checked = -not $NoInstalarOCR
    $ocrCheck.Location = New-Object System.Drawing.Point(32, 288)
    $ocrCheck.Size = New-Object System.Drawing.Size(470, 24)
    $form.Controls.Add($ocrCheck)

    $codexCheck = New-Object System.Windows.Forms.CheckBox
    $codexCheck.Text = "Preparar integracion con Codex App sin API"
    $codexCheck.Checked = -not $NoPrepararCodex
    $codexCheck.Location = New-Object System.Drawing.Point(32, 316)
    $codexCheck.Size = New-Object System.Drawing.Size(470, 24)
    $form.Controls.Add($codexCheck)

    $openCheck = New-Object System.Windows.Forms.CheckBox
    $openCheck.Text = "Abrir la app al terminar"
    $openCheck.Checked = -not $NoAbrirAlFinal
    $openCheck.Location = New-Object System.Drawing.Point(32, 344)
    $openCheck.Size = New-Object System.Drawing.Size(420, 24)
    $form.Controls.Add($openCheck)

    $hint = New-Object System.Windows.Forms.Label
    $hint.Text = "Codex es opcional: el instalador solo lo detecta y prepara la app para usarlo si ya esta instalado."
    $hint.ForeColor = [System.Drawing.Color]::DimGray
    $hint.Location = New-Object System.Drawing.Point(30, 374)
    $hint.Size = New-Object System.Drawing.Size(580, 32)
    $form.Controls.Add($hint)

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "Cancelar"
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $cancel.Location = New-Object System.Drawing.Point(420, 414)
    $cancel.Size = New-Object System.Drawing.Size(90, 30)
    $form.Controls.Add($cancel)

    $install = New-Object System.Windows.Forms.Button
    $install.Text = "Instalar"
    $install.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $install.Location = New-Object System.Drawing.Point(520, 414)
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
        }
    })
    $dataBrowse.Add_Click({
        $folderDialog.Description = "Elige donde guardar datos y descargas"
        $folderDialog.SelectedPath = $dataBox.Text
        if ($folderDialog.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
            $dataBox.Text = $folderDialog.SelectedPath
        }
    })

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
Copy-AppFiles -From $SourceRoot -To $TargetRoot

Write-Step "Preparando carpetas de datos"
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
