$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Create .venv and install requirements first."
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --name "AI Flashcard Generator" `
    --windowed `
    --icon "assets\icon.ico" `
    --add-data "languages.json;." `
    --add-data "assets\icon.png;assets" `
    --collect-submodules "PySide6.QtCore" `
    --collect-submodules "PySide6.QtGui" `
    --collect-submodules "PySide6.QtWidgets" `
    --collect-submodules "PySide6.QtMultimedia" `
    --exclude-module "PySide6.QtWebEngineCore" `
    --exclude-module "PySide6.QtWebEngineQuick" `
    --exclude-module "PySide6.QtWebEngineWidgets" `
    --exclude-module "PySide6.QtQuick" `
    --exclude-module "PySide6.QtQml" `
    "flashcard-generator.py"

$distExe = Join-Path $PSScriptRoot "dist\AI Flashcard Generator\AI Flashcard Generator.exe"
$buildExe = Join-Path $PSScriptRoot "build\AI Flashcard Generator\AI Flashcard Generator.exe"

if (Test-Path $buildExe) {
    Remove-Item $buildExe
}

if (-not (Test-Path $distExe)) {
    throw "Build completed, but executable was not found at: $distExe"
}

Write-Host ""
Write-Host "Executable created:"
Write-Host $distExe
