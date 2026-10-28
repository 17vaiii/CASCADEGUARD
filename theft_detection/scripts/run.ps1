# Starts the API, which also serves the built frontend, at http://127.0.0.1:8000
# The first start trains the detection models if none are saved (about 1-2 minutes).
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\backend"
.\.venv\Scripts\python.exe -m uvicorn gridwatch.api.main:app --host 127.0.0.1 --port 8000
Pop-Location
