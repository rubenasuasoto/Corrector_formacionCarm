param(
    [switch]$Forzar
)

$ErrorActionPreference = "Stop"

function Test-Tesseract {
    $cmd = Get-Command "tesseract.exe" -ErrorAction SilentlyContinue
    if (-not $cmd) {
        return $false
    }
    & tesseract --version | Out-Null
    return $LASTEXITCODE -eq 0
}

function Find-TesseractRoot {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Tesseract-OCR"),
        "C:\Program Files\Tesseract-OCR",
        "C:\Program Files (x86)\Tesseract-OCR"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "tesseract.exe")) {
            return $candidate
        }
    }
    return ""
}

function Install-SpanishLanguage {
    $root = Find-TesseractRoot
    if (-not $root) {
        Write-Host "No se encontro la carpeta de Tesseract para instalar idioma espanol." -ForegroundColor Yellow
        return
    }
    $tessdata = Join-Path $root "tessdata"
    New-Item -ItemType Directory -Path $tessdata -Force | Out-Null
    $spa = Join-Path $tessdata "spa.traineddata"
    if (Test-Path -LiteralPath $spa) {
        Write-Host "Idioma espanol de OCR ya instalado." -ForegroundColor Green
        return
    }
    Write-Host "Instalando idioma espanol para OCR..." -ForegroundColor Cyan
    Invoke-WebRequest `
        -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/spa.traineddata" `
        -OutFile $spa `
        -UseBasicParsing
}

if ((Test-Tesseract) -and -not $Forzar) {
    Write-Host "Tesseract OCR ya esta disponible." -ForegroundColor Green
    Install-SpanishLanguage
    exit 0
}

$winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
if (-not $winget) {
    throw "No se encontro winget. Instala Tesseract OCR manualmente y asegurate de que tesseract.exe este en el PATH."
}

Write-Host "Instalando Tesseract OCR con winget..." -ForegroundColor Cyan
& winget install --id UB-Mannheim.TesseractOCR --exact --accept-package-agreements --accept-source-agreements
if ($LASTEXITCODE -ne 0) {
    throw "La instalacion de Tesseract OCR fallo con codigo $LASTEXITCODE."
}

Write-Host ""
Install-SpanishLanguage
Write-Host "Tesseract OCR instalado. Cierra y vuelve a abrir la app para refrescar el PATH." -ForegroundColor Green
