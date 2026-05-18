param(
    [switch]$Forzar
)

$ErrorActionPreference = "Stop"

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

function Add-TesseractToPath {
    $root = Find-TesseractRoot
    if ($root) {
        $env:Path = "$root;$env:Path"
    }
    return $root
}

function Get-TesseractCommand {
    $cmd = Get-Command "tesseract.exe" -ErrorAction SilentlyContinue
    if ($cmd) {
        return [string]$cmd.Source
    }
    $root = Add-TesseractToPath
    if ($root) {
        $candidate = Join-Path $root "tesseract.exe"
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return ""
}

function Test-Tesseract {
    $cmd = Get-TesseractCommand
    if (-not $cmd) {
        return $false
    }
    & $cmd --version | Out-Null
    return $LASTEXITCODE -eq 0
}

function Install-SpanishLanguage {
    $root = Find-TesseractRoot
    if (-not $root) {
        Write-Host "No se encontro la carpeta de Tesseract para instalar idioma espanol." -ForegroundColor Yellow
        return $false
    }
    $tessdata = Join-Path $root "tessdata"
    New-Item -ItemType Directory -Path $tessdata -Force | Out-Null
    $spa = Join-Path $tessdata "spa.traineddata"
    if (Test-Path -LiteralPath $spa) {
        Write-Host "Idioma espanol de OCR ya instalado." -ForegroundColor Green
        return $true
    }
    Write-Host "Instalando idioma espanol para OCR..." -ForegroundColor Cyan
    try {
        Invoke-WebRequest `
            -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/spa.traineddata" `
            -OutFile $spa `
            -UseBasicParsing
        return $true
    } catch {
        Write-Host "No se pudo descargar el idioma espanol de OCR. La app seguira funcionando; OCR usara ingles si esta disponible o marcara revision manual." -ForegroundColor Yellow
        Write-Host "Detalle: $_" -ForegroundColor Yellow
        return $false
    }
}

if ((Test-Tesseract) -and -not $Forzar) {
    Write-Host "Tesseract OCR ya esta disponible." -ForegroundColor Green
    [void](Install-SpanishLanguage)
    exit 0
}

$winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
if (-not $winget) {
    throw "No se encontro winget. Instala Tesseract OCR manualmente y asegurate de que tesseract.exe este en el PATH."
}

Write-Host "Instalando Tesseract OCR con winget..." -ForegroundColor Cyan
& $winget.Source install --id UB-Mannheim.TesseractOCR --source winget --exact --accept-package-agreements --accept-source-agreements --silent
if ($LASTEXITCODE -ne 0) {
    throw "La instalacion de Tesseract OCR fallo con codigo $LASTEXITCODE."
}

Add-TesseractToPath | Out-Null
if (-not (Test-Tesseract)) {
    throw "Tesseract OCR parece instalado, pero no se pudo ejecutar. Reinicia Windows o instala Tesseract manualmente si el problema persiste."
}

Write-Host ""
[void](Install-SpanishLanguage)
Write-Host "Tesseract OCR instalado. La app intentara detectarlo automaticamente aunque el PATH de Windows tarde en refrescar." -ForegroundColor Green
