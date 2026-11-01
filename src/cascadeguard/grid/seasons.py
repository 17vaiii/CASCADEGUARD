# OWNER: P1 | STATUS: ACTIVE
"""Seasonal profiles and dispatch limits for the Sharavathi transmission corridor.

Implements P1-4: monsoon, post-monsoon, and summer seasonal configurations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
import pandapower as pp


@dataclass
class SeasonProfile:
    name: str
    months: list[int]
    description: str
    reservoir_level_pct: float
    max_generation_mw: float
    min_generation_mw: float
    ramp_rate_mw_per_min: float
    daily_energy_limit_mwh: float
    inflow_cumecs: float
    corridor_load_scale: float
    source: str = "assumed"


def load_season_profiles(seasons_dir: str | Path | None = None) -> dict[str, SeasonProfile]:
    """Load seasonal profiles from YAML configuration files."""
    if seasons_dir is None:
        seasons_dir = Path(__file__).resolve().parents[3] / "configs" / "seasons"
    else:
        seasons_dir = Path(seasons_dir)

    profiles: dict[str, SeasonProfile] = {}
    if seasons_dir.exists():
        for yml_file in seasons_dir.glob("*.yaml"):
            try:
                with open(yml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and "name" in data:
                    name = data["name"]
                    profiles[name] = SeasonProfile(
                        name=name,
                        months=data.get("months", []),
                        description=data.get("description", ""),
                        reservoir_level_pct=float(data.get("reservoir_level_pct", 50.0)),
                        max_generation_mw=float(data.get("max_generation_mw", 600.0)),
                        min_generation_mw=float(data.get("min_generation_mw", 150.0)),
                        ramp_rate_mw_per_min=float(data.get("ramp_rate_mw_per_min", 10.0)),
                        daily_energy_limit_mwh=float(data.get("daily_energy_limit_mwh", 12000.0)),
                        inflow_cumecs=float(data.get("inflow_cumecs", 100.0)),
                        corridor_load_scale=float(data.get("corridor_load_scale", 1.0)),
                    )
            except Exception:
                pass

    if not profiles:
        # Fallback defaults
        profiles["monsoon"] = SeasonProfile("monsoon", [6,7,8,9,10], "Monsoon high hydro", 85.0, 900.0, 200.0, 15.0, 18000.0, 450.0, 0.85)
        profiles["post_monsoon"] = SeasonProfile("post_monsoon", [11,12,1,2], "Post-monsoon balanced", 65.0, 600.0, 150.0, 12.0, 12000.0, 120.0, 0.95)
        profiles["summer"] = SeasonProfile("summer", [3,4,5], "Summer peak demand", 35.0, 350.0, 100.0, 8.0, 6000.0, 30.0, 1.15)

    return profiles


def apply_season(net: pp.pandapowerNet, season: SeasonProfile) -> None:
    """Scale network loads and set hydro limits according to the season."""
    scale = season.corridor_load_scale
    if "bus_loads_mw" in net:
        for bus_idx, base_p in net["bus_loads_mw"].items():
            mask = net.load.bus == bus_idx
            if mask.any():
                net.load.loc[mask, "p_mw"] = base_p * scale

    net["season_name"] = season.name
    net["season_load_scale"] = scale
