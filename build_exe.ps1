# Build the standalone Windows converter (Onedir is more reliable with
# antivirus scanners than a one-file self-extracting executable).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name NastranConverter `
    --paths $root `
    NastranConverter.py

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$zip = Join-Path $root "dist\NastranConverter-win64.zip"
Compress-Archive `
    -Path (Join-Path $root "dist\NastranConverter\*") `
    -DestinationPath $zip `
    -Force

Write-Host ""
Write-Host "EXE:  dist\NastranConverter\NastranConverter.exe"
Write-Host "ZIP:  dist\NastranConverter-win64.zip"
