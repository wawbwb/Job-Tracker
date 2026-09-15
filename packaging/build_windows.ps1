param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $Python -m PyInstaller --noconfirm packaging/JobTracker.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
    & $Python packaging/verify_bundle.py
    if ($LASTEXITCODE -ne 0) { throw "Release archive verification failed" }
    Write-Host "Created: $projectRoot/dist/JobTracker.exe"
} finally {
    Pop-Location
}
