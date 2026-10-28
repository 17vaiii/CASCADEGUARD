#!/usr/bin/env sh
# One-time setup on Linux / macOS. Requires python3.12 and Node.js 20+.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cd "$ROOT/frontend"
npm ci
npm run build
echo "Setup complete. Start the app with: ./scripts/run.sh"
