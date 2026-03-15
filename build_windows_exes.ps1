$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$commonArgs = @(
    '--noconfirm',
    '--clean',
    '--onefile',
    '--windowed'
)

$pawlyArgs = @(
    '--name', 'Pawly',
    '--distpath', $root,
    '--workpath', "$root\build\Pawly",
    '--specpath', "$root\build\Pawly",
    '--add-data', "$root\Cat Sprite Sheet.png;.",
    '--add-data', "$root\Coin_Gems;Coin_Gems",
    '--add-data', "$root\pipo-popupemotes Split images;pipo-popupemotes Split images",
    "$root\desktop_cat.py"
)

$panelArgs = @(
    '--name', 'PawlyPanel',
    '--distpath', $root,
    '--workpath', "$root\build\PawlyPanel",
    '--specpath', "$root\build\PawlyPanel",
    "$root\desktop_cat_panel.pyw"
)

python -m PyInstaller @commonArgs @pawlyArgs
python -m PyInstaller @commonArgs @panelArgs

Write-Host "Built: $root\Pawly.exe"
Write-Host "Built: $root\PawlyPanel.exe"
