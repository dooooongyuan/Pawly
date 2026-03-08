$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m PyInstaller --noconfirm --clean --onefile --windowed --name Pawly --distpath $root --workpath "$root\build\Pawly" --specpath "$root\build\Pawly" "$root\desktop_cat.py"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PawlyPanel --distpath $root --workpath "$root\build\PawlyPanel" --specpath "$root\build\PawlyPanel" "$root\desktop_cat_panel.pyw"

Write-Host "Built: $root\Pawly.exe"
Write-Host "Built: $root\PawlyPanel.exe"
