param(
    [switch]$SinPruebaOffline,
    [switch]$CrearTag
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "No existe .venv. Ejecuta primero instalar_windows.cmd" -ForegroundColor Red
    exit 1
}

$ArgsList = @("preparar_release.py")
if ($SinPruebaOffline) {
    $ArgsList += "--sin-prueba-offline"
}
if ($CrearTag) {
    $ArgsList += "--crear-tag"
}

& $VenvPython @ArgsList
exit $LASTEXITCODE
