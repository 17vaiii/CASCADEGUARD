"""Paths and global settings."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

DATA_DIR = Path(os.environ.get("GRIDWATCH_DATA_DIR", PROJECT_DIR / "data" / "generated"))
MODELS_DIR = Path(os.environ.get("GRIDWATCH_MODELS_DIR", BACKEND_DIR / "artifacts" / "models"))
RESULTS_DIR = Path(os.environ.get("GRIDWATCH_RESULTS_DIR", BACKEND_DIR / "artifacts" / "results"))
DB_PATH = Path(os.environ.get("GRIDWATCH_DB", DATA_DIR / "gridwatch.sqlite3"))
FRONTEND_DIST = Path(os.environ.get("GRIDWATCH_FRONTEND_DIST", PROJECT_DIR / "frontend" / "dist"))

# Simulation clock. Every step is one simulated hour; meter values are hourly
# energy (kWh), which numerically equals the hourly-average power in kW.
STEP_HOURS = 1.0
HISTORY_DAYS = 28  # clean reference period used to learn each consumer's expected profile
OBSERVATION_DAYS = 14  # the window shown on the playback timeline
SYNTHETIC_START = "2026-03-02T00:00:00"  # a Monday; the calendar itself is synthetic

for _d in (DATA_DIR, MODELS_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
