# OWNER: P4 | NEEDS: P1,P3 | STATUS: ACTIVE
"""Train the P3 cascade GNN on snapshots of the *root* P1 corridor model, with hidden load.

P3's shipped checkpoint gives nearly flat predictions on root-corridor snapshots, so it cannot
show the effect of theft (T9). This module generates labelled scenarios with the root P1 engine
across seasons and hidden-load levels, then calls P3's unchanged ``train_pipeline``. The result
goes to ``data/models/root_gnn/``; P3's own ``data/models/cascade_gnn.pt`` is not modified.

    PYTHONPATH=src python -m cascadeguard.theft.root_gnn
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cascadeguard.theft import REPO_ROOT
from cascadeguard.theft.hidden_load import corridor_state, metered_substation_mw, snapshot_from_net

ROOT_GNN_DIR = REPO_ROOT / "data" / "models" / "root_gnn"
SEASONS = ("monsoon", "post_monsoon", "summer")
HIDDEN_LEVELS = (0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12)


def _hidden(season: str, level: float, rng: np.random.Generator) -> list[dict[str, Any]]:
    """Hidden load per substation: ``level`` x metered load, unevenly split (unseen by T9's ratios)."""
    return [{"bus_id": sub, "hidden_load_mw": float(mw * level * rng.uniform(0.3, 1.7)), "power_factor": 0.95}
            for sub, mw in metered_substation_mw(season).items()]


def _contingencies(n_lines: int, n2: int, rng: np.random.Generator) -> list[list[int]]:
    pairs = [(i, j) for i in range(n_lines) for j in range(i + 1, n_lines)]
    return [[i] for i in range(n_lines)] + [list(pairs[p]) for p in rng.choice(len(pairs), n2, replace=False)]


def _simulate_state(net: Any, season: str, tag: str, conts: list[list[int]], load_scale: float) -> list[dict[str, Any]]:
    from cascadeguard.sim.cascade_engine import simulate_cascade
    rows = []
    for trips in conts:
        r = simulate_cascade(net, trips)
        # A failed AC solve is a voltage collapse: all load lost, every line counted as failed.
        lost = float(r.load_lost_mw) if r.converged else float(net["total_load_mw"])
        failed = [int(x) for x in r.failed_lines] if r.converged else [int(i) for i in net.line.index]
        rows.append({
            **snapshot_from_net(net, trips, f"{tag}|{trips}"), "season": season, "load_scale": load_scale,
            "contingency_k": len(trips), "failed_lines": failed, "load_lost_mw": lost, "converged": bool(r.converged),
        })
    return rows


def _job(season: str, level: float, with_tie: bool, n2: int, seed: int) -> list[dict[str, Any]]:
    from pandapower.auxiliary import LoadflowNotConverged
    rng = np.random.default_rng(seed)
    hidden = _hidden(season, level, rng)
    try:
        if with_tie:
            from cascadeguard.mitigation.network import build_state
            net = build_state(season, hidden).net
        else:
            net = corridor_state(season, hidden)
    except LoadflowNotConverged:      # the pre-contingency state itself collapses: not usable as input
        return []
    return _simulate_state(net, season, f"{season}|{level}|tie={with_tie}", _contingencies(len(net.line), n2, rng), 1.0 + level)


def generate(output: Path, n2: int = 30, n_jobs: int = 4, seed: int = 42) -> pd.DataFrame:
    from joblib import Parallel, delayed
    jobs = []
    for s_i, season in enumerate(SEASONS):
        for l_i, level in enumerate(HIDDEN_LEVELS):
            job_seed = seed + 100 * s_i + l_i
            jobs.append((season, level, False, n2, job_seed))
            if l_i % 2 == 0:
                jobs.append((season, level, True, n2, job_seed + 50))
    res = Parallel(n_jobs=n_jobs)(delayed(_job)(*j) for j in jobs)
    df = pd.DataFrame([r for rows in res for r in rows])
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output, index=False)
    return df


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n2", type=int, default=30)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--dataset", default=str(REPO_ROOT / "data" / "processed" / "root_gnn_dataset.parquet"))
    a = p.parse_args()
    t0 = time.time()
    df = generate(Path(a.dataset), a.n2, a.jobs)
    print(f"{len(df)} scenarios in {time.time() - t0:.0f}s; lose load: {(df.load_lost_mw > 0).mean():.2f}", flush=True)
    from cascadeguard.cascade_ml.train import train_pipeline
    train_pipeline(dataset_path=a.dataset, output_dir=str(ROOT_GNN_DIR), epochs=a.epochs)


if __name__ == "__main__":
    main()
