# One-time setup on Windows (PowerShell). Requires Python 3.12 (the "py" launcher) and Node.js 20+.
# Keep the project in a reasonably short path (Windows limits paths to 260 characters by default;
# some npm packages run install scripts deep inside node_modules).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Step([string]$what, [scriptblock]$cmd) {
    Write-Host "==> $what"
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE). Fix the error above and re-run setup." }
}

Push-Location "$root\backend"
try {
    Invoke-Step "Create Python virtual environment" { py -3.12 -m venv .venv }
    Invoke-Step "Upgrade pip" { .\.venv\Scripts\python.exe -m pip install --upgrade pip }
    Invoke-Step "Install backend packages" { .\.venv\Scripts\python.exe -m pip install -r requirements.txt }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    Invoke-Step "Install frontend packages" { npm ci }
    Invoke-Step "Build the frontend" { npm run build }
} finally { Pop-Location }

Write-Host "Setup complete. Start the app with: .\scripts\run.ps1"
