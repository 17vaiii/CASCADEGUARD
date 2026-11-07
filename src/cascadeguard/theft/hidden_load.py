# OWNER: P4 | NEEDS: P1,P3 | STATUS: ACTIVE
"""T9 / P4-10: theft-aware grid state - the link between the two pillars.

Unmetered (stolen) demand makes real line loading higher than SCADA shows. This module:

1. turns the T2 energy-balance estimate into a **hidden-load vector** per corridor substation
   (``theft_detection``-style THEFT_LOAD_VECTOR fields: ``bus_id``, ``hidden_load_mw``,
   ``power_factor``, ``confidence``, ``source = suspected_unmetered_load``);
2. builds three states of the P1 corridor model for the same season:
   * ``scada``  - metered demand only (what operators see),
   * ``aware``  - metered demand + P4's *estimated* hidden load,
   * ``truth``  - metered demand + the *true* hidden load (simulation ground truth);
3. runs the P1 AC cascade simulator on all three for the same contingencies and also queries
   the P3 cascade GNN on each pre-contingency snapshot;
4. reports how much modelling hidden load improves load-loss prediction and cascade detection.

Hidden load is injected as real pandapower loads (never by editing meter values). P1/P3 code
is used read-only.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandapower as pp

from cascadeguard.theft import REPO_ROOT, load_config


# ---------------------------------------------------------------------------
# Hidden-load vector and corridor states
# ---------------------------------------------------------------------------

def hidden_load_vector(ntl_ratio: pd.DataFrame, metered_mw: dict[str, float], intensity: float,
                       column: str = "est_ntl_ratio", power_factor: float = 0.95,
                       scenario_id: str = "theft_aware", confidence: dict[str, float] | None = None
                       ) -> list[dict[str, Any]]:
    """Hidden MW per substation = metered MW x NTL ratio x intensity (THEFT_LOAD_VECTOR records)."""
    out = []
    for row in ntl_ratio.itertuples(index=False):
        if row.substation not in metered_mw:
            continue
        mw = max(0.0, float(getattr(row, column)) * metered_mw[row.substation] * intensity)
        out.append({"scenario_id": scenario_id, "bus_id": row.substation, "hidden_load_mw": round(mw, 4),
                    "power_factor": power_factor,
                    "confidence": None if confidence is None else confidence.get(row.substation),
                    "source": "suspected_unmetered_load"})
    return out


def corridor_state(season: str, hidden: list[dict[str, Any]] | None = None) -> pp.pandapowerNet:
    """P1 corridor model for a season, plus hidden loads; returns a solved net."""
    from cascadeguard.grid.corridor_model import build_corridor_network
    from cascadeguard.grid.seasons import apply_season, load_season_profiles
    net = build_corridor_network()
    apply_season(net, load_season_profiles()[season])
    bus_loads = dict(net["bus_loads_mw"])
    scale = float(net.get("season_load_scale", 1.0))
    bus_loads = {b: p * scale for b, p in bus_loads.items()}
    for item in hidden or []:
        mw = float(item["hidden_load_mw"])
        if mw <= 0:
            continue
        bus = net["name_to_idx"][item["bus_id"]]
        q = mw * np.tan(np.arccos(float(item.get("power_factor") or 0.95)))
        pp.create_load(net, bus=bus, p_mw=mw, q_mvar=q, name=f"HIDDEN_{item['bus_id']}")
        bus_loads[bus] = bus_loads.get(bus, 0.0) + mw
    # Keep cascade-engine metadata consistent with the loads actually present (P1's
    # apply_season leaves total_load_mw at the unscaled value; see docs/p4/p4.md §5).
    net["bus_loads_mw"] = bus_loads
    net["total_load_mw"] = float(net.load.p_mw.sum())
    pp.runpp(net, algorithm="nr", init="dc", numba=False)
    return net


def metered_substation_mw(season: str) -> dict[str, float]:
    net = corridor_state(season)
    idx_to_name = {v: k for k, v in net["name_to_idx"].items()}
    return {idx_to_name[int(r.bus)]: float(r.p_mw) for r in net.load.itertuples()}


def snapshot_from_net(net: pp.pandapowerNet, initial_trips: list[int], scenario_id: str = "live") -> dict[str, Any]:
    """Pre-contingency snapshot in the ``cascade_graph_v1`` field layout used by P3's graph builder.

    Bus P/Q use pandapower's ``res_bus`` sign convention (load positive).
    """
    lines = net.line
    return {
        "scenario_id": scenario_id,
        "bus_ids": [int(b) for b in net.bus.index],
        "pre_bus_vm_pu": net.res_bus.vm_pu.astype(float).tolist(),
        "pre_bus_p_mw": net.res_bus.p_mw.astype(float).tolist(),
        "pre_bus_q_mvar": net.res_bus.q_mvar.astype(float).tolist(),
        "line_ids": [int(i) for i in lines.index],
        "line_from_bus": lines.from_bus.astype(int).tolist(),
        "line_to_bus": lines.to_bus.astype(int).tolist(),
        "pre_line_r_ohm": (lines.r_ohm_per_km * lines.length_km).astype(float).tolist(),
        "pre_line_x_ohm": (lines.x_ohm_per_km * lines.length_km).astype(float).tolist(),
        "pre_line_loading_pct": net.res_line.loading_percent.astype(float).tolist(),
        "initial_trips": [int(t) for t in initial_trips],
    }


# ---------------------------------------------------------------------------
# P3 GNN (read-only use of the trained checkpoint)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_gnn(path: str) -> tuple[Any, float, float] | None:
    ckpt_path = Path(path)
    if not ckpt_path.exists():
        return None
    import torch
    from cascadeguard.cascade_ml.gnn import CascadeGNN
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model = CascadeGNN()
    model.load_state_dict(ckpt.get("model_state", ckpt))
    model.eval()
    return model, float(ckpt.get("temperature", 1.0)), float(ckpt.get("conformal_q", 0.0))


def default_checkpoint() -> Path:
    """GNN retrained on root-corridor snapshots if present (``theft.root_gnn``), else P3's file."""
    root = REPO_ROOT / "data" / "models" / "root_gnn" / "cascade_gnn.pt"
    return root if root.exists() else REPO_ROOT / "data" / "models" / "cascade_gnn.pt"


def gnn_predict(snapshot: dict[str, Any], checkpoint: str | Path | None = None) -> dict[str, Any] | None:
    """Cascade GNN prediction for one snapshot; ``None`` if no checkpoint is available."""
    ckpt = Path(checkpoint or default_checkpoint())
    loaded = _load_gnn(str(ckpt))
    if loaded is None:
        return None
    import torch
    from cascadeguard.cascade_ml.graph_builder import build_graph
    model, temperature, conformal_q = loaded
    g = build_graph(snapshot, include_targets=False)
    with torch.no_grad():
        out = model(x=g.x, edge_index=g.edge_index, edge_attr=g.edge_attr,
                    line_from=g.edge_index[0, :g.num_lines], line_to=g.edge_index[1, :g.num_lines],
                    line_features=g.line_features)
    probs = torch.sigmoid(out["line_logits"] / max(temperature, 1e-4)).numpy()
    top = np.argsort(-probs)[:5]
    loss = float(out["load_loss_mw"].item())
    return {"load_lost_mw": loss, "has_cascade_prob": float(out["has_cascade_prob"].item()),
            "cascade_size": float(out["cascade_size"].item()), "checkpoint": ckpt.parent.name,
            "load_lost_interval_mw": [max(0.0, loss - conformal_q), loss + conformal_q],
            "top_line_failure_probs": [{"line": int(i), "prob": float(probs[i])} for i in top]}


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------

def _simulate(net: pp.pandapowerNet, trips: list[int]) -> dict[str, Any]:
    from cascadeguard.sim.cascade_engine import simulate_cascade
    r = simulate_cascade(net, trips)
    if not r.converged:
        # The AC solve failed after the event: voltage collapse. P1's engine stops there and
        # reports only the load shed so far, so count all load as lost here.
        total = float(net["total_load_mw"])
        return {"load_lost_mw": total, "bengaluru_load_lost_mw": float(r.bengaluru_load_mw),
                "lines_tripped": int(r.total_lines_tripped), "cascade": True, "converged": False}
    return {"load_lost_mw": float(r.load_lost_mw), "bengaluru_load_lost_mw": float(r.bengaluru_load_lost_mw),
            "lines_tripped": int(r.total_lines_tripped), "cascade": bool(r.total_lines_tripped > len(trips)),
            "converged": True}


def _contingencies(n_lines: int, n2_sample: int, seed: int) -> list[list[int]]:
    rng = np.random.default_rng(seed)
    n1 = [[i] for i in range(n_lines)]
    pairs = [(i, j) for i in range(n_lines) for j in range(i + 1, n_lines)]
    pick = rng.choice(len(pairs), size=min(n2_sample, len(pairs)), replace=False)
    return n1 + [list(pairs[p]) for p in sorted(pick)]


def _run_state(net: pp.pandapowerNet, contingencies: list[list[int]], n_jobs: int) -> list[dict[str, Any]]:
    if n_jobs == 1:
        return [_simulate(net, c) for c in contingencies]
    from joblib import Parallel, delayed
    return Parallel(n_jobs=n_jobs)(delayed(_simulate)(net, c) for c in contingencies)


def theft_aware_experiment(ntl_ratio: pd.DataFrame, config: dict[str, Any] | None = None,
                           n_jobs: int = 4, use_gnn: bool = True, seed: int = 42) -> dict[str, Any]:
    """Compare SCADA-only vs theft-aware cascade prediction against the hidden-load truth."""
    cfg = (config or load_config())["hidden_load"]
    rows: list[dict[str, Any]] = []
    states_out: list[dict[str, Any]] = []
    for season in cfg["seasons"]:
        scada = corridor_state(season)
        metered = metered_substation_mw(season)
        conts = _contingencies(len(scada.line), int(cfg["n2_sample"]), seed)
        scada_sim = _run_state(scada, conts, n_jobs)
        scada_gnn = [gnn_predict(snapshot_from_net(scada, c)) for c in conts] if use_gnn else [None] * len(conts)
        for intensity in cfg["intensity"]:
            vec_true = hidden_load_vector(ntl_ratio, metered, intensity, "true_ntl_ratio", cfg["power_factor"])
            vec_est = hidden_load_vector(ntl_ratio, metered, intensity, "est_ntl_ratio", cfg["power_factor"])
            truth, aware = corridor_state(season, vec_true), corridor_state(season, vec_est)
            states_out.append({
                "season": season, "intensity": intensity,
                "true_hidden_mw": sum(v["hidden_load_mw"] for v in vec_true),
                "est_hidden_mw": sum(v["hidden_load_mw"] for v in vec_est),
                "max_loading_pct": {"scada": float(scada.res_line.loading_percent.max()),
                                    "aware": float(aware.res_line.loading_percent.max()),
                                    "truth": float(truth.res_line.loading_percent.max())},
            })
            truth_sim, aware_sim = _run_state(truth, conts, n_jobs), _run_state(aware, conts, n_jobs)
            aware_gnn = [gnn_predict(snapshot_from_net(aware, c)) for c in conts] if use_gnn else [None] * len(conts)
            for c, t, s, a, sg, ag in zip(conts, truth_sim, scada_sim, aware_sim, scada_gnn, aware_gnn):
                rows.append({
                    "season": season, "intensity": intensity, "k": len(c), "trips": c,
                    "truth_load_lost": t["load_lost_mw"], "truth_cascade": t["cascade"], "truth_collapse": not t["converged"],
                    "scada_sim_load_lost": s["load_lost_mw"], "scada_sim_cascade": s["cascade"],
                    "aware_sim_load_lost": a["load_lost_mw"], "aware_sim_cascade": a["cascade"],
                    "scada_gnn_load_lost": sg["load_lost_mw"] if sg else np.nan,
                    "aware_gnn_load_lost": ag["load_lost_mw"] if ag else np.nan,
                    "scada_gnn_cascade_prob": sg["has_cascade_prob"] if sg else np.nan,
                    "aware_gnn_cascade_prob": ag["has_cascade_prob"] if ag else np.nan,
                })
    df = pd.DataFrame(rows)
    return {"rows": df, "states": states_out, "summary": summarise_experiment(df)}


def summarise_experiment(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for (season, intensity), g in df.groupby(["season", "intensity"]):
        truth_c = g.truth_cascade.astype(bool)
        rec: dict[str, Any] = {"season": season, "intensity": float(intensity), "n": int(len(g)),
                               "truth_cascades": int(truth_c.sum()), "truth_voltage_collapses": int(g.truth_collapse.sum())}
        for view in ("scada", "aware"):
            pred_c = g[f"{view}_sim_cascade"].astype(bool)
            rec[f"{view}_sim_mae_mw"] = float((g[f"{view}_sim_load_lost"] - g.truth_load_lost).abs().mean())
            rec[f"{view}_sim_cascade_accuracy"] = float((pred_c == truth_c).mean())
            rec[f"{view}_sim_missed_cascades"] = int((truth_c & ~pred_c).sum())
            gnn = g[f"{view}_gnn_load_lost"]
            if gnn.notna().any():
                rec[f"{view}_gnn_mae_mw"] = float((gnn - g.truth_load_lost).abs().mean())
                prob = g[f"{view}_gnn_cascade_prob"]
                rec[f"{view}_gnn_cascade_accuracy"] = float(((prob >= 0.5) == truth_c).mean())
                rec[f"{view}_gnn_mean_load_lost_mw"] = float(gnn.mean())
                rec[f"{view}_gnn_mean_cascade_prob"] = float(prob.mean())
        rec["truth_mean_load_lost_mw"] = float(g.truth_load_lost.mean())
        rec["sim_mae_improvement_mw"] = rec["scada_sim_mae_mw"] - rec["aware_sim_mae_mw"]
        if "scada_gnn_mae_mw" in rec:
            rec["gnn_mae_improvement_mw"] = rec["scada_gnn_mae_mw"] - rec["aware_gnn_mae_mw"]
        out.append(rec)
    return out
