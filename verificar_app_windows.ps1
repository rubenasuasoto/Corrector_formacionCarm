param(
    [switch]$Instalacion,
    [switch]$SinPruebaOffline,
    [switch]$SinEndpoints
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "No existe .venv. Ejecuta primero instalar_windows.cmd" -ForegroundColor Red
    exit 1
}

$ArgsList = @("verificar_app.py")
if ($Instalacion) {
    $ArgsList += "--instalacion"
}
if ($SinPruebaOffline) {
    $ArgsList += "--sin-prueba-offline"
}
if ($SinEndpoints) {
    $ArgsList += "--sin-endpoints"
}

& $VenvPython @ArgsList
exit $LASTEXITCODE
