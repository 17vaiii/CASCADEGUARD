#!/usr/bin/env bash
# OWNER: P1 | STATUS: ACTIVE
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Running CascadeGuard-Sharavathi scaffold generator..."
python3 "$SCRIPT_DIR/scaffold.py"
echo "Scaffold complete."
