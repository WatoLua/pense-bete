<#
.SYNOPSIS
Builds the standalone Windows version of Pense-bete.

.DESCRIPTION
Pense-bete.exe with Python and PySide6 in it, in dist\Pense-bete, checked with its
self-test, and its archive dist\pense-bete-windows.zip, which the installer downloads on
machines without Python. GitHub Actions runs it for every release; from a clone:
  powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"
$app = Join-Path $dist "Pense-bete"

python -m pip install --upgrade pyinstaller -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE) { throw "pip failed" }
# QtSvg is imported by name: nothing in the code does, but Qt's SVG image plugin, which
# draws the icons, needs it.
python -m PyInstaller --noconfirm --clean --windowed --name Pense-bete `
    --icon (Join-Path $root "icon.ico") --hidden-import PySide6.QtSvg --exclude-module tkinter `
    --distpath $dist --workpath (Join-Path $root "build") --specpath (Join-Path $root "build") `
    (Join-Path $root "pense_bete.py")
if ($LASTEXITCODE) { throw "PyInstaller failed" }
# Beside the executable, where the application and the installer look for them.
foreach ($file in "icon.svg", "icon.ico", "LICENSE", "install.ps1") {
    Copy-Item -LiteralPath (Join-Path $root $file) -Destination $app
}

# A module or Qt plugin left out shows here, before the build is published.
$report = Join-Path $dist "self-test.txt"
$process = Start-Process -FilePath (Join-Path $app "Pense-bete.exe") `
    -ArgumentList @("--self-test", "`"$report`"") -Wait -PassThru
if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report }
if ($process.ExitCode) { throw "The self-test failed (exit code $($process.ExitCode))." }

$zip = Join-Path $dist "pense-bete-windows.zip"
Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
# The archive holds the Pense-bete directory, as GitHub's source archives hold theirs.
Compress-Archive -LiteralPath $app -DestinationPath $zip
Write-Host "Built $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"
