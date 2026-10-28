#!/usr/bin/env sh
# Starts the API, which also serves the built frontend, at http://127.0.0.1:8000
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
exec .venv/bin/python -m uvicorn gridwatch.api.main:app --host 127.0.0.1 --port 8000
