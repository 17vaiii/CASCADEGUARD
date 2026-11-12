$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$BuildRuntime = Join-Path $env:TEMP 'CascadeGuardLauncherBuild'
$BuildOutput = Join-Path $env:TEMP 'CascadeGuardLauncherPyInstaller'
New-Item -ItemType Directory -Force -Path $BuildRuntime | Out-Null
New-Item -ItemType Directory -Force -Path $BuildOutput | Out-Null

$env:PYTHONPATH = $BuildRuntime
& py -3.12 -m pip install --quiet --target $BuildRuntime pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Could not install the launcher build tool.' }

& py -3.12 -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name CascadeGuard `
    --distpath $ProjectRoot `
    --workpath (Join-Path $BuildOutput 'build') `
    --specpath (Join-Path $BuildOutput 'spec') `
    (Join-Path $PSScriptRoot 'CascadeGuardLauncher.py')
if ($LASTEXITCODE -ne 0) { throw 'CascadeGuard.exe build failed.' }

Write-Host "Created $ProjectRoot\CascadeGuard.exe"
