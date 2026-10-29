"""
simdata/cascade_scenarios.py — Generate cascade contingency datasets.

Runs N-1 and N-2 contingency simulations across all seasons and exports
labeled Parquet datasets for downstream cascade prediction ML (Person 2).

Public API
----------
generate_cascade_dataset(out_dir, seasons, k_range, seed, n_jobs)
    → pd.DataFrame  (also saved as parquet)
"""

from __future__ import annotations

import itertools
import json
import logging
from functools import lru_cache
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pandapower as pp

from grid.cascade import (
    CascadeResult,
    build_cascade_net,
    simulate_cascade,
)
from grid.config import TopologyConfig, load_topology
from grid.hydro import apply_season, get_all_seasons

log = logging.getLogger("cascade_data")

_DEFAULT_OUT = Path(__file__).parent.parent / "data" / "processed"


@lru_cache(maxsize=64)
def _base_snapshot_features(season_name: str, load_scale: float,
                            topology_json: str) -> dict:
    """Solve/cache the pre-contingency operating point for a scenario group.

    The baseline depends on the operating point (season/load/topology), not on
    which line contingency is subsequently applied. Caching avoids repeating
    this extra power flow for every N-k row, including in parallel workers.
    """
    topology = TopologyConfig.model_validate_json(topology_json)
    net = build_cascade_net(topology, load_scale=load_scale)
    apply_season(net, get_all_seasons()[season_name])
    pp.runpp(net, algorithm="nr", init="dc", max_iteration=50,
             tolerance_mva=1e-6, numba=False)
    return {
        "graph_feature_schema": "cascade_graph_v1",
        "graph_feature_timing": "pre_contingency",
        "bus_ids": [str(x) for x in net.bus.name.tolist()],
        "pre_bus_vm_pu": net.res_bus.vm_pu.astype(float).round(6).tolist(),
        "pre_bus_p_mw": net.res_bus.p_mw.astype(float).round(6).tolist(),
        "pre_bus_q_mvar": net.res_bus.q_mvar.astype(float).round(6).tolist(),
        "line_ids": [int(x) for x in net.line.index.tolist()],
        "line_names": [str(x) for x in net.line.name.tolist()],
        "line_from_bus": [int(x) for x in net.line.from_bus.tolist()],
        "line_to_bus": [int(x) for x in net.line.to_bus.tolist()],
        "pre_line_r_ohm": (net.line.r_ohm_per_km * net.line.length_km).astype(float).round(6).tolist(),
        "pre_line_x_ohm": (net.line.x_ohm_per_km * net.line.length_km).astype(float).round(6).tolist(),
        "pre_line_loading_pct": net.res_line.loading_percent.astype(float).round(6).tolist(),
    }


def _result_to_row(
    result: CascadeResult,
    season_name: str,
    load_scale: float,
    contingency_k: int,
    net,
    seed: int = 42,
    topology_json: str | None = None,
) -> dict:
    """Convert a CascadeResult into a flat dict for a DataFrame row."""
    # Build per-line final loading
    final_loading_cols = {}
    for li in net.line.index:
        final_loading_cols[f"line_{li}_loading"] = result.final_line_loading.get(li)

    # Build per-bus final voltage
    final_vm_cols = {}
    for bi in net.bus.index:
        final_vm_cols[f"bus_{bi}_vm_pu"] = result.final_vm_pu.get(bi)

    failed_names = [str(net.line.at[li, "name"]) for li in result.failed_lines
                    if li in net.line.index]
    snapshot = (_base_snapshot_features(season_name, float(load_scale), topology_json)
                if topology_json else {})
    return {
        "scenario_id": f"{season_name}-ls{load_scale:.4f}-k{contingency_k}-" + "-".join(map(str, result.initial_trips)),
        "seed": seed,
        "season": season_name,
        "load_scale": load_scale,
        "contingency_k": contingency_k,
        "failed_lines": result.failed_lines,
        "failed_line_names": failed_names,
        "affected_buses": result.affected_buses,
        "initial_trips": result.initial_trips,
        "initial_trip_names": result.initial_trip_names,
        "cascade_depth": result.cascade_depth,
        "total_lines_tripped": result.total_lines_tripped,
        "total_lines": result.total_lines,
        "lines_surviving": result.lines_surviving,
        "load_served_mw": result.load_served_mw,
        "load_lost_mw": result.load_lost_mw,
        "bengaluru_load_mw": result.bengaluru_load_mw,
        "bengaluru_load_lost_mw": result.bengaluru_load_lost_mw,
        "bengaluru_load_shed_pct": result.bengaluru_load_shed_pct,
        "bengaluru_blackout": result.bengaluru_load_mw > 0 and result.bengaluru_load_lost_mw >= result.bengaluru_load_mw - 0.1,
        "total_load_mw": result.total_load_mw,
        "load_shed_pct": result.load_shed_pct,
        "gen_mw": result.gen_mw,
        "hydro_generation_mw": result.hydro_generation_mw,
        "loss_mw": result.loss_mw,
        "islands": result.islands,
        "blackout": result.blackout,
        "converged": result.converged,
        **snapshot,
        "hydro_max_generation_mw": net.get("max_gen_mw"),
        "hydro_min_generation_mw": net.get("min_gen_mw"),
        "hydro_ramp_rate_mw_per_min": net.get("ramp_rate_mw_per_min"),
        "hydro_daily_energy_limit_mwh": net.get("daily_energy_mwh"),
        "hydro_dispatch_mw": net.get("hydro_dispatch_mw"),
        "hydro_energy_remaining_mwh": net.get("hydro_energy_remaining_mwh"),
        "reservoir_level_mcm": net.get("reservoir_level_mcm"),
        "hydro_ramp_limited": net.get("hydro_ramp_limited"),
        "hydro_energy_limited": net.get("hydro_energy_limited"),
        "reservoir_level_pct": net.get("reservoir_pct"),
        **final_loading_cols,
        **final_vm_cols,
    }


def _run_contingency(args: tuple) -> Optional[dict]:
    """Worker function for parallel execution."""
    trips, season_name, load_scale, k, topology, seed = args
    try:
        net = build_cascade_net(topology, load_scale=load_scale)
        season_cfg = get_all_seasons()
        if season_name in season_cfg:
            apply_season(net, season_cfg[season_name])
        result = simulate_cascade(net, list(trips))
        return _result_to_row(result, season_name, load_scale, k, net, seed,
                              topology.model_dump_json())
    except Exception as e:
        log.warning(f"Contingency {trips} season={season_name} failed: {e}")
        return None


def generate_cascade_dataset(
    out_dir: Path | None = None,
    seasons: list[str] | None = None,
    k_range: tuple[int, int] = (1, 2),
    load_scale_points: list[float] | None = None,
    seed: int = 42,
    n_jobs: int = 1,
) -> pd.DataFrame:
    """
    Generate a full cascade contingency dataset.

    Parameters
    ----------
    out_dir : Path
        Output directory (default: data/processed/).
    seasons : list[str]
        Which seasons to simulate (default: all).
    k_range : tuple
        Range of N-k contingencies to simulate (default: N-1 and N-2).
    load_scale_points : list[float]
        Load scale multipliers to sweep (on top of seasonal scaling).
    seed : int
        Random seed for reproducibility.
    n_jobs : int
        Number of parallel workers (1 = sequential).

    Returns
    -------
    pd.DataFrame
        Full dataset of cascade outcomes.
    """
    out_dir = out_dir or _DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    if k_range[0] < 1 or k_range[1] < k_range[0] or k_range[1] > 3:
        raise ValueError("k_range must satisfy 1 <= minimum <= maximum <= 3")
    if load_scale_points is not None and any(float(x) <= 0 for x in load_scale_points):
        raise ValueError("load_scale_points must contain positive multipliers")

    topology = load_topology()
    all_seasons = get_all_seasons()
    season_names = seasons or list(all_seasons.keys())
    unknown_seasons = sorted(set(season_names) - set(all_seasons))
    if unknown_seasons:
        raise ValueError(f"Unknown season(s): {unknown_seasons}")

    if load_scale_points is None:
        load_scale_points = [1.0]

    # Build a reference net to get line count
    ref_net = build_cascade_net(topology, load_scale=1.0)
    all_lines = list(ref_net.line.index)
    n_lines = len(all_lines)

    log.info(f"Cascade dataset: {n_lines} lines, "
             f"seasons={season_names}, k={k_range}")

    # Build work items
    work: list[tuple] = []
    for season_name in season_names:
        for scale in load_scale_points:
            for k in range(k_range[0], k_range[1] + 1):
                if k == 1:
                    for li in all_lines:
                        work.append(([li], season_name, scale, k, topology, seed))
                elif k == 2:
                    for combo in itertools.combinations(all_lines, 2):
                        work.append((list(combo), season_name, scale, k, topology, seed))
                elif k == 3:
                    for combo in itertools.combinations(all_lines, 3):
                        work.append((list(combo), season_name, scale, k, topology, seed))

    log.info(f"  Total contingency simulations: {len(work)}")
    t0 = time.perf_counter()

    # Run (sequential or parallel)
    rows: list[dict] = []
    if n_jobs > 1:
        try:
            from joblib import Parallel, delayed
            results = Parallel(n_jobs=n_jobs, backend="loky")(
                delayed(_run_contingency)(w) for w in work
            )
            rows = [r for r in results if r is not None]
        except ImportError:
            log.warning("joblib not installed; falling back to sequential")
            rows = [r for w in work if (r := _run_contingency(w)) is not None]
    else:
        for i, w in enumerate(work):
            r = _run_contingency(w)
            if r is not None:
                rows.append(r)
            if (i + 1) % 50 == 0:
                log.info(f"  {i + 1}/{len(work)} done")

    elapsed = time.perf_counter() - t0
    log.info(f"  Completed {len(rows)} scenarios in {elapsed:.1f}s")

    df = pd.DataFrame(rows)
    out_path = out_dir / "cascade_dataset.parquet"
    df.to_parquet(out_path, index=False)
    log.info(f"  Saved → {out_path}")

    # Summary statistics
    if len(df) > 0:
        log.info(f"  Blackout rate: {df.blackout.mean():.1%}")
        log.info(f"  Mean load shed: {df.load_shed_pct.mean():.1f}%")
        log.info(f"  Max load shed: {df.load_shed_pct.max():.1f}%")

    return df


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Generate cascade dataset")
    parser.add_argument("--seasons", nargs="+", default=None)
    parser.add_argument("--k-max", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()

    generate_cascade_dataset(
        seasons=args.seasons,
        k_range=(1, args.k_max),
        seed=args.seed,
        n_jobs=args.jobs,
    )

