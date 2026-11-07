# OWNER: P4 | STATUS: ACTIVE
"""P4 theft and loss analytics (PRD T1-T10).

Outputs are *leads for inspection*, never verdicts. All data is synthetic, and every
electrical or behavioural parameter is an assumption documented in
``configs/theft/models.yaml``.
"""

from __future__ import annotations

import copy
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "configs" / "theft" / "models.yaml"

THEFT_TYPES = ("meter_bypass", "meter_stop", "night_tapping", "hooking", "temporary_tampering")
LOOKALIKE_TYPES = ("rooftop_solar", "new_appliance", "vacancy")
DISCLAIMER = ("Simulated data. Scores are leads for field inspection, not evidence of theft; "
              "a human inspection is required before any action.")


@lru_cache(maxsize=4)
def _load_config_cached(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Return a deep copy of the P4 configuration (callers may mutate it freely)."""
    return copy.deepcopy(_load_config_cached(str(path or CONFIG_PATH)))


def hashed_id(consumer_id: str, salt: str = "cascadeguard-demo") -> str:
    """Short salted hash of a consumer ID for shared demos (PRD 7.5 / 9: identifiers hashed)."""
    return "H-" + hashlib.sha256(f"{salt}:{consumer_id}".encode("utf-8")).hexdigest()[:10]
