# OWNER: P5 | NEEDS: P2,P3,P4 | STATUS: ACTIVE
"""Data access for the dashboard: live simulation calls plus P4/P5 artifacts on disk.

Everything degrades gracefully: a missing artifact returns ``None`` and the view shows how to
produce it, so the dashboard also runs on a fresh clone.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import pandas as pd

from cascadeguard.mitigation import REPO_ROOT

THEFT_DIR = REPO_ROOT / "data" / "processed" / "theft"
THEFT_METRICS = REPO_ROOT / "data" / "models" / "theft" / "theft_metrics.json"
MITIGATION_DIR = REPO_ROOT / "data" / "processed" / "mitigation"
MITIGATION_METRICS = REPO_ROOT / "data" / "models" / "mitigation" / "mitigation_metrics.json"
CASE_LIBRARY = REPO_ROOT / "data" / "models" / "mitigation" / "cascade_case_library.pkl"
CASCADE_ML_METRICS = REPO_ROOT / "data" / "models" / "cascade_ml_metrics.json"


def read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def read_parquet(path: Path) -> pd.DataFrame | None:
    return pd.read_parquet(path) if path.exists() else None


def theft_leads() -> list[dict[str, Any]] | None:
    p = THEFT_DIR / "inspection_leads.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def case_library():
    if not CASE_LIBRARY.exists():
        return None
    with open(CASE_LIBRARY, "rb") as fh:
        return pickle.load(fh)


def hidden_load_vector(season: str, intensity: float, column: str = "est_ntl_ratio") -> list[dict[str, Any]] | None:
    """P4's estimated hidden load per substation (T9 handoff) for a season and intensity."""
    ratio = read_parquet(THEFT_DIR / "ntl_ratio_by_substation.parquet")
    if ratio is None:
        return None
    from cascadeguard.theft.hidden_load import hidden_load_vector as hv, metered_substation_mw
    return hv(ratio, metered_substation_mw(season), intensity, column)


def corridor_frame(net) -> pd.DataFrame:
    """One row per dual-circuit section for plotting: km range, loading of each circuit."""
    rows = []
    sec_km = net["section_km"]
    for sec, (a, b) in net["cascade_pairs"].items():
        km0, km1 = sec_km[sec]
        def load(i):
            if not net.line.at[i, "in_service"]:
                return None
            try:
                v = float(net.res_line.loading_percent.at[i])
                return None if pd.isna(v) else v
            except Exception:
                return None
        rows.append({"section": sec, "km_from": km0, "km_to": km1, "line_a": a, "line_b": b,
                     "load_a": load(a), "load_b": load(b),
                     "name": str(net.line.at[a, "name"]).split("_", 2)[-1]})
    return pd.DataFrame(rows)
