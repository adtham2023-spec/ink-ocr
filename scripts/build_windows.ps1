param([switch]$InstallDependencies, [string]$PythonExecutable)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $localPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    $PythonExecutable = if (Test-Path -LiteralPath $localPython) { $localPython } else { 'python' }
}
Push-Location -LiteralPath $repoRoot
try {
    if ($InstallDependencies) {
        & $PythonExecutable -m pip install -r requirements-lock.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    }
    & $PythonExecutable scripts\fetch_tessdata.py
    if ($LASTEXITCODE -ne 0) { throw 'Language model verification failed.' }
    $appIcon = Join-Path $repoRoot 'assets\ink.ico'
    $tessdata = Join-Path $repoRoot 'assets\tessdata'
    & $PythonExecutable -m PyInstaller --noconfirm --clean --windowed --onedir --name InkOCR --icon $appIcon --collect-all tesserocr --add-data "$tessdata;tessdata" --collect-all rapidocr_onnxruntime --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-all opencc --collect-binaries onnxruntime --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --distpath dist --workpath build\work --specpath build app.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
    & $PythonExecutable scripts\package_release.py
    if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
} finally {
    Pop-Location
}
