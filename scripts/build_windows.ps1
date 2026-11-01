param([switch]$InstallDependencies)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repoRoot
try {
    if ($InstallDependencies) {
        python -m pip install -r requirements-lock.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    }
    $appIcon = Join-Path $repoRoot 'assets\ink.ico'
    python -m PyInstaller --noconfirm --clean --windowed --onedir --name InkOCR --icon $appIcon --collect-all rapidocr_onnxruntime --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-all opencc --collect-binaries onnxruntime --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --distpath dist --workpath build\work --specpath build app.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
    python scripts\package_release.py
    if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
} finally {
    Pop-Location
}
