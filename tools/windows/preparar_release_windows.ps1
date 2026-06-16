param(
    [switch]$SinPruebaOffline,
    [switch]$CrearTag
)

$ErrorActionPreference = "Stop"
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = [IO.Path]::GetFullPath((Join-Path $ToolsDir "..\.."))
Set-Location -LiteralPath $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "No existe .venv. Ejecuta primero instalar_windows.cmd" -ForegroundColor Red
    exit 1
}

$ArgsList = @((Join-Path $ToolsDir "preparar_release.py"))
if ($SinPruebaOffline) {
    $ArgsList += "--sin-prueba-offline"
}
if ($CrearTag) {
    $ArgsList += "--crear-tag"
}

& $VenvPython @ArgsList
exit $LASTEXITCODE
