param([string]$Python = "E:\conda_envs\AirControl\python.exe")
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & $Python -m pip install -r packaging/requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }
    & $Python scripts/package_release.py
    if ($LASTEXITCODE -ne 0) { throw "Release build failed" }
} finally { Pop-Location }
