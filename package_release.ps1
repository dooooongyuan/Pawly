$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$releaseRoot = Join-Path $root 'dist-release'
$bundleName = 'Pawly-windows-x64'
$bundleDir = Join-Path $releaseRoot $bundleName
$zipPath = Join-Path $releaseRoot "$bundleName.zip"
$shaPath = Join-Path $releaseRoot "$bundleName.zip.sha256"

if (Test-Path $bundleDir) {
    Remove-Item $bundleDir -Recurse -Force
}
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
if (Test-Path $shaPath) {
    Remove-Item $shaPath -Force
}

New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null

& (Join-Path $root 'build_windows_exes.ps1')

$filesToCopy = @(
    'Pawly.exe',
    'PawlyPanel.exe',
    'README.md',
    'LICENSE',
    'THIRD_PARTY_NOTICES.md',
    'desktop_cat_panel_config.example.json'
)

foreach ($file in $filesToCopy) {
    Copy-Item (Join-Path $root $file) (Join-Path $bundleDir $file) -Force
}

$startHere = @(
    'Pawly Windows Release'
    '====================='
    ''
    '1. Unzip this package'
    '2. Double-click PawlyPanel.exe'
    '3. Enter your OpenClaw URL'
    '4. Click the Start button in the panel'
    ''
    'This release already includes the required runtime assets.'
    'End users do not need to install Python.'
) -join [Environment]::NewLine

Set-Content -Path (Join-Path $bundleDir 'START_HERE.txt') -Value $startHere -Encoding utf8

Compress-Archive -Path (Join-Path $bundleDir '*') -DestinationPath $zipPath -Force

$hash = (Get-FileHash -Algorithm SHA256 -Path $zipPath).Hash.ToLowerInvariant()
"$hash  $bundleName.zip" | Set-Content -Path $shaPath -Encoding ascii

Write-Host "Packaged: $zipPath"
Write-Host "SHA256:   $shaPath"
