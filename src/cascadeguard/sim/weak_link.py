# OWNER: P1 | STATUS: ACTIVE
"""Weak-link ranking module identifying critical corridor transmission branches.

Implements P1-7:
  - Ranks corridor line elements by seasonal vulnerability and load loss
  - Produces seasonal weak-link reports
"""

from __future__ import annotations

from typing import Any
import pandas as pd
import pandapower as pp

from cascadeguard.grid.corridor_model import build_corridor_network
from cascadeguard.grid.seasons import apply_season, load_season_profiles
from cascadeguard.sim.cascade_engine import simulate_cascade


def generate_seasonal_weak_link_report(
    seasons: list[str] | None = None,
    k: int = 1,
) -> pd.DataFrame:
    """Evaluate N-k line trips across seasons and rank lines by severity."""
    all_seasons = load_season_profiles()
    if seasons is None:
        seasons = ["monsoon", "post_monsoon", "summer"]

    rows = []
    base_net = build_corridor_network()
    num_lines = len(base_net.line)

    for season_name in seasons:
        if season_name not in all_seasons:
            continue
        season_profile = all_seasons[season_name]
        net = build_corridor_network()
        apply_season(net, season_profile)

        for line_idx in range(num_lines):
            res = simulate_cascade(net, initial_trips=[line_idx])
            rows.append({
                "season": season_name,
                "line_index": line_idx,
                "line_name": net.line.at[line_idx, "name"],
                "from_bus": int(net.line.at[line_idx, "from_bus"]),
                "to_bus": int(net.line.at[line_idx, "to_bus"]),
                "total_lines_tripped": res.total_lines_tripped,
                "cascade_depth": res.cascade_depth,
                "load_lost_mw": res.load_lost_mw,
                "bengaluru_load_lost_mw": res.bengaluru_load_lost_mw,
                "blackout": res.blackout,
            })

    df = pd.DataFrame(rows)
    df.sort_values(by=["load_lost_mw", "total_lines_tripped"], ascending=False, inplace=True)
    return df
