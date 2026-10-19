# Build dist\Tokie.exe (single file, no console window, with the app icon).
#   pip install -r requirements-dev.txt
#   .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python tools\make_icon.py

# A short work path avoids Windows' 260-character limit when the project sits in a deep folder.
$work = Join-Path $env:LOCALAPPDATA "Temp\tokie_build"
$icon = Join-Path $PSScriptRoot "assets\tokie.ico"  # absolute: PyInstaller resolves relative paths against --specpath
python -m PyInstaller --noconfirm --onefile --windowed --name Tokie `
    --icon $icon --add-data "${icon};assets" `
    --distpath dist --workpath $work --specpath $work tokie.py

Get-Item dist\Tokie.exe | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) }}
