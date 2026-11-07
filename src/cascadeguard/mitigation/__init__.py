# OWNER: P5 | STATUS: ACTIVE
"""P5 mitigation (PRD R9, H2, H3): minimal verified remedial actions for corridor contingencies.

Role separation (PRD §8): the GNN predicts, OR-Tools decides, the P1 simulator verifies, the
LLM only explains. Every recommendation is advisory and needs operator approval.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "configs" / "mitigation" / "optimizer.yaml"
ADVISORY = ("Advisory recommendation from a simulation model. It does not operate any equipment; "
            "an operator must review and approve every action.")


@lru_cache(maxsize=4)
def _cached(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return copy.deepcopy(_cached(str(path or CONFIG_PATH)))
