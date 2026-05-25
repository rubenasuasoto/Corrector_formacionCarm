param(
    [switch]$EliminarDatos,
    [switch]$EliminarPendientes,
    [switch]$EliminarTemporal,
    [switch]$EliminarCursos,
    [switch]$Silencioso,
    [switch]$PermitirRepositorio
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootFull = [IO.Path]::GetFullPath($Root)
$AppName = "Corrector CARM"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Corrector CARM"
$script:ProgressForm = $null
$script:ProgressLog = $null
$script:ProgressLabel = $null
$script:ProgressBar = $null
$script:ProgressClose = $null

function Add-ProgressLine([string]$Message) {
    if ($script:ProgressLog) {
        $script:ProgressLog.AppendText($Message + [Environment]::NewLine)
        $script:ProgressLog.SelectionStart = $script:ProgressLog.TextLength
        $script:ProgressLog.ScrollToCaret()
        [System.Windows.Forms.Application]::DoEvents()
    }
}

function Write-Step($Message) {
    if (-not $Silencioso) {
        Write-Host ""
        Write-Host "==> $Message" -ForegroundColor Cyan
        Add-ProgressLine "==> $Message"
    }
}

function Start-UninstallProgress {
    if ($Silencioso) { return }
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $script:ProgressForm = New-Object System.Windows.Forms.Form
        $script:ProgressForm.Text = "Desinstalando Corrector CARM"
        $script:ProgressForm.StartPosition = "CenterScreen"
        $script:ProgressForm.FormBorderStyle = "FixedDialog"
        $script:ProgressForm.MaximizeBox = $false
        $script:ProgressForm.MinimizeBox = $false
        $script:ProgressForm.ControlBox = $false
        $script:ProgressForm.ClientSize = New-Object System.Drawing.Size(680, 360)
        $iconPath = Join-Path $RootFull "assets\corrector_carm.ico"
        if (Test-Path -LiteralPath $iconPath) {
            try { $script:ProgressForm.Icon = New-Object System.Drawing.Icon($iconPath) } catch {}
        }

        $script:ProgressLabel = New-Object System.Windows.Forms.Label
        $script:ProgressLabel.Text = "Quitando la app y aplicando las opciones elegidas"
        $script:ProgressLabel.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
        $script:ProgressLabel.Location = New-Object System.Drawing.Point(22, 20)
        $script:ProgressLabel.Size = New-Object System.Drawing.Size(620, 28)
        $script:ProgressForm.Controls.Add($script:ProgressLabel)

        $script:ProgressBar = New-Object System.Windows.Forms.ProgressBar
        $script:ProgressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
        $script:ProgressBar.MarqueeAnimationSpeed = 35
        $script:ProgressBar.Location = New-Object System.Drawing.Point(24, 62)
        $script:ProgressBar.Size = New-Object System.Drawing.Size(630, 18)
        $script:ProgressForm.Controls.Add($script:ProgressBar)

        $script:ProgressLog = New-Object System.Windows.Forms.TextBox
        $script:ProgressLog.Multiline = $true
        $script:ProgressLog.ReadOnly = $true
        $script:ProgressLog.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
        $script:ProgressLog.Font = New-Object System.Drawing.Font("Consolas", 8.5)
        $script:ProgressLog.Location = New-Object System.Drawing.Point(24, 98)
        $script:ProgressLog.Size = New-Object System.Drawing.Size(630, 205)
        $script:ProgressForm.Controls.Add($script:ProgressLog)

        $script:ProgressClose = New-Object System.Windows.Forms.Button
        $script:ProgressClose.Text = "Cerrar"
        $script:ProgressClose.Enabled = $false
        $script:ProgressClose.Location = New-Object System.Drawing.Point(564, 318)
        $script:ProgressClose.Size = New-Object System.Drawing.Size(90, 28)
        $script:ProgressClose.Add_Click({ $script:ProgressForm.Close() })
        $script:ProgressForm.Controls.Add($script:ProgressClose)

        $script:ProgressForm.Show()
        [System.Windows.Forms.Application]::DoEvents()
    } catch {}
}

function Complete-UninstallProgress {
    param([string]$Message)
    if ($Silencioso -or -not $script:ProgressForm) { return }
    $script:ProgressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Blocks
    $script:ProgressBar.MarqueeAnimationSpeed = 0
    $script:ProgressBar.Value = 100
    $script:ProgressLabel.Text = $Message
    $script:ProgressClose.Enabled = $true
    $script:ProgressForm.ControlBox = $true
    Add-ProgressLine $Message
    while ($script:ProgressForm.Visible) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
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

function Select-DataRemovalInteractive {
    param([array]$DataItems)
    if ($Silencioso -or $EliminarDatos -or $EliminarPendientes -or $EliminarTemporal -or $EliminarCursos -or $DataItems.Count -eq 0) {
        return @()
    }
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $form = New-Object System.Windows.Forms.Form
        $form.Text = "Desinstalar Corrector CARM"
        $form.StartPosition = "CenterScreen"
        $form.FormBorderStyle = "FixedDialog"
        $form.MaximizeBox = $false
        $form.MinimizeBox = $false
        $form.ClientSize = New-Object System.Drawing.Size(620, 310)

        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Elige que datos locales quieres borrar"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
        $title.Location = New-Object System.Drawing.Point(20, 18)
        $title.Size = New-Object System.Drawing.Size(560, 28)
        $form.Controls.Add($title)

        $hint = New-Object System.Windows.Forms.Label
        $hint.Text = "Por defecto se desinstala la app y se conservan entregas, prompts, CSV y caches. Marca solo lo que quieras eliminar."
        $hint.Location = New-Object System.Drawing.Point(22, 52)
        $hint.Size = New-Object System.Drawing.Size(560, 40)
        $form.Controls.Add($hint)

        $list = New-Object System.Windows.Forms.CheckedListBox
        $list.Location = New-Object System.Drawing.Point(24, 98)
        $list.Size = New-Object System.Drawing.Size(560, 130)
        $list.CheckOnClick = $true
        foreach ($item in $DataItems) {
            [void]$list.Items.Add("$($item.Name): $($item.Path)", $false)
        }
        $form.Controls.Add($list)

        $checkAll = New-Object System.Windows.Forms.Button
        $checkAll.Text = "Borrar todo"
        $checkAll.Location = New-Object System.Drawing.Point(24, 234)
        $checkAll.Size = New-Object System.Drawing.Size(100, 28)
        $checkAll.Add_Click({
            for ($i = 0; $i -lt $list.Items.Count; $i++) {
                $list.SetItemChecked($i, $true)
            }
        })
        $form.Controls.Add($checkAll)

        $keepAll = New-Object System.Windows.Forms.Button
        $keepAll.Text = "Conservar todo"
        $keepAll.Location = New-Object System.Drawing.Point(134, 234)
        $keepAll.Size = New-Object System.Drawing.Size(120, 28)
        $keepAll.Add_Click({
            for ($i = 0; $i -lt $list.Items.Count; $i++) {
                $list.SetItemChecked($i, $false)
            }
        })
        $form.Controls.Add($keepAll)

        $cancel = New-Object System.Windows.Forms.Button
        $cancel.Text = "Cancelar"
        $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $cancel.Location = New-Object System.Drawing.Point(390, 254)
        $cancel.Size = New-Object System.Drawing.Size(90, 30)
        $form.Controls.Add($cancel)

        $ok = New-Object System.Windows.Forms.Button
        $ok.Text = "Desinstalar"
        $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $ok.Location = New-Object System.Drawing.Point(492, 254)
        $ok.Size = New-Object System.Drawing.Size(90, 30)
        $form.Controls.Add($ok)
        $form.AcceptButton = $ok
        $form.CancelButton = $cancel

        $result = $form.ShowDialog()
        if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
            Write-Host "Desinstalacion cancelada por el usuario." -ForegroundColor Yellow
            exit 0
        }
        $selected = @()
        foreach ($index in $list.CheckedIndices) {
            $selected += $DataItems[[int]$index].Key
        }
        return $selected
    } catch {
        Write-Host "No se pudo abrir selector grafico de datos; se conservaran los datos locales. Detalle: $_" -ForegroundColor Yellow
        return @()
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
    Remove-IfExists (Join-Path $startup "Corrector CARM.vbs")
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
$dataItems = @()
if ($config) {
    $known = @(
        @{ Key = "pendientes"; Name = "Pendientes, entregas y prompts"; Path = $config.pendientes_dir },
        @{ Key = "temporal"; Name = "CSV, resumenes y salidas temporales"; Path = $config.temporal_dir },
        @{ Key = "cursos"; Name = "Cursos, caches por curso y proyectos Codex"; Path = $config.courses_dir }
    )
    foreach ($item in $known) {
        if ($item.Path) {
            $fullPath = [IO.Path]::GetFullPath([string]$item.Path)
            if (-not ($dataItems | Where-Object { $_.Path -eq $fullPath })) {
                $dataItems += [pscustomobject]@{ Key = $item.Key; Name = $item.Name; Path = $fullPath }
            }
        }
    }
}

$interactiveDeleteKeys = Select-DataRemovalInteractive -DataItems $dataItems

Start-UninstallProgress
Stop-AppProcesses
Remove-Shortcuts
Remove-UninstallEntry

$deleteKeys = @()
if ($EliminarDatos) {
    $deleteKeys = @("pendientes", "temporal", "cursos")
} else {
    if ($EliminarPendientes) { $deleteKeys += "pendientes" }
    if ($EliminarTemporal) { $deleteKeys += "temporal" }
    if ($EliminarCursos) { $deleteKeys += "cursos" }
    $deleteKeys += $interactiveDeleteKeys
}
$deleteKeys = @($deleteKeys | Sort-Object -Unique)

if ($deleteKeys.Count -gt 0) {
    foreach ($item in $dataItems) {
        if ($deleteKeys -contains $item.Key -and $item.Path -and (Test-Path -LiteralPath $item.Path)) {
            Write-Step "Eliminando datos locales: $($item.Path)"
            Remove-Item -LiteralPath $item.Path -Force -Recurse -ErrorAction SilentlyContinue
        }
    }
}

Remove-AppFolder $RootFull

if (-not $Silencioso) {
    Write-Host ""
    Write-Host "Corrector CARM desinstalado." -ForegroundColor Green
    $kept = @($dataItems | Where-Object { $deleteKeys -notcontains $_.Key })
    if ($kept.Count -gt 0) {
        Write-Host "Datos conservados:" -ForegroundColor Yellow
        $kept | ForEach-Object { Write-Host " - $($_.Name): $($_.Path)" }
    }
    Complete-UninstallProgress "Corrector CARM desinstalado"
}
