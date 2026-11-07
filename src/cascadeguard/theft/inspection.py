# OWNER: P4 | STATUS: ACTIVE
"""T6 / P4-8: inspection prioritisation by expected recovered energy and travel cost.

Two kinds of lead compete for the same limited crew visits:

* **consumer leads** - a suspicion probability and an estimate of the energy the meter is
  missing (drop below the peer-adjusted expectation);
* **network leads** - a DT whose energy-balance residual is *not* explained by consumer leads
  below it (hooking / direct tapping does not show on any consumer meter).

Strategies compared (PRD §10 "energy recovered per inspection vs random and rule-based"):
``random``, ``rule_based`` (largest consumption drop), ``score`` (probability only),
``expected_value`` (probability x energy) and ``value_route`` (expected value net of travel,
built as greedy crew routes from each substation depot).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from cascadeguard.theft import load_config


def consumer_energy_at_stake(features: pd.DataFrame, recent_intervals: int) -> pd.Series:
    """kWh the meter is missing vs a peer-adjusted expectation, over the scoring window."""
    peer_med_ratio = (features.f_ratio_recent / features.f_peer_ratio).replace([np.inf, -np.inf], np.nan)
    expected = features.f_hist_mean_kwh * peer_med_ratio.fillna(1.0).clip(0.5, 1.5)
    gap = (expected - features.f_recent_mean_kwh).clip(lower=0).fillna(0.0)
    return gap * recent_intervals


def _dist(ax: float, ay: float, bx: np.ndarray, by: np.ndarray) -> np.ndarray:
    return np.hypot(bx - ax, by - ay)


def route_cost_km(leads: pd.DataFrame, depots: dict[str, tuple[float, float]]) -> float:
    """Nearest-neighbour tour length from each lead's substation depot (round trip)."""
    total = 0.0
    for sub, grp in leads.groupby("substation"):
        x0, y0 = depots[sub]
        cx, cy = x0, y0
        todo = grp[["x_km", "y_km"]].to_numpy().copy()
        while len(todo):
            d = _dist(cx, cy, todo[:, 0], todo[:, 1])
            j = int(np.argmin(d))
            total += float(d[j])
            cx, cy = todo[j]
            todo = np.delete(todo, j, axis=0)
        total += float(np.hypot(cx - x0, cy - y0))
    return total


def value_route_selection(leads: pd.DataFrame, k: int, depots: dict[str, tuple[float, float]],
                          tariff: float, cost_km: float, cost_visit: float, crews: int = 2) -> list[int]:
    """Greedy prize-collecting routes: at each step the best (value - travel - visit) next stop.

    ``crews`` crews per substation each keep a current position; the global best move over all
    crews is taken until ``k`` visits are scheduled or no move has positive net value.
    """
    lx, ly = leads.x_km.to_numpy(), leads.y_km.to_numpy()
    ev = (leads.prob * leads.est_kwh).to_numpy() * tariff
    subs = leads.substation.to_numpy()
    crew_pos = [(s, *depots[s]) for s in depots for _ in range(crews)]
    chosen: list[int] = []
    free = np.ones(len(leads), dtype=bool)
    while len(chosen) < k and free.any():
        best = (-np.inf, -1, -1)
        for ci, (s, cx, cy) in enumerate(crew_pos):
            mask = free & (subs == s)
            if not mask.any():
                continue
            idx = np.where(mask)[0]
            net = ev[idx] - cost_km * _dist(cx, cy, lx[idx], ly[idx]) - cost_visit
            j = int(np.argmax(net))
            if net[j] > best[0]:
                best = (net[j], ci, idx[j])
        if best[1] < 0 or best[0] <= 0:
            break
        _, ci, j = best
        chosen.append(int(j))
        free[j] = False
        crew_pos[ci] = (crew_pos[ci][0], lx[j], ly[j])
    return chosen


def select(leads: pd.DataFrame, strategy: str, k: int, depots: dict[str, tuple[float, float]],
           cfg: dict[str, Any], seed: int = 42) -> list[int]:
    if strategy == "random":
        return list(np.random.default_rng(seed).permutation(len(leads))[:k])
    if strategy == "rule_based":
        return list(np.argsort(-leads.rule_score.to_numpy(), kind="stable")[:k])
    if strategy == "score":
        return list(np.argsort(-leads.prob.to_numpy(), kind="stable")[:k])
    if strategy == "expected_value":
        return list(np.argsort(-(leads.prob * leads.est_kwh).to_numpy(), kind="stable")[:k])
    if strategy == "value_route":
        return value_route_selection(leads, k, depots, cfg["tariff_inr_per_kwh"], cfg["cost_inr_per_km"],
                                     cfg["cost_inr_per_visit"], int(cfg["crews"]))
    raise ValueError(f"unknown strategy {strategy}")


def evaluate_campaign(leads: pd.DataFrame, chosen: list[int], depots: dict[str, tuple[float, float]],
                      cfg: dict[str, Any]) -> dict[str, Any]:
    """Hits, true energy recovered, travel and net value of one campaign (simulated truth)."""
    sel = leads.iloc[chosen]
    km = route_cost_km(sel, depots) if len(sel) else 0.0
    recovered = float(sel.true_recoverable_kwh.sum())
    value = recovered * cfg["tariff_inr_per_kwh"] - km * cfg["cost_inr_per_km"] - len(sel) * cfg["cost_inr_per_visit"]
    return {
        "visits": int(len(sel)), "hits": int(sel.is_hit.sum()),
        "precision": float(sel.is_hit.mean()) if len(sel) else float("nan"),
        "network_leads": int((sel.lead_type == "network").sum()),
        "recovered_kwh": recovered, "recovered_kwh_per_visit": recovered / max(len(sel), 1),
        "travel_km": km, "net_value_inr": value,
    }


def compare_strategies(leads: pd.DataFrame, k: int, depots: dict[str, tuple[float, float]],
                       config: dict[str, Any] | None = None, seed: int = 42,
                       random_repeats: int = 20) -> pd.DataFrame:
    cfg = (config or load_config())["inspection"]
    rows = []
    for strategy in ("random", "rule_based", "score", "expected_value", "value_route"):
        if strategy == "random":
            runs = [evaluate_campaign(leads, select(leads, "random", k, depots, cfg, seed + r), depots, cfg)
                    for r in range(random_repeats)]
            res = {key: float(np.mean([r[key] for r in runs])) for key in runs[0]}
        else:
            res = evaluate_campaign(leads, select(leads, strategy, k, depots, cfg, seed), depots, cfg)
        rows.append({"strategy": strategy, **res})
    return pd.DataFrame(rows)


def build_lead_table(consumers: pd.DataFrame, features: pd.DataFrame, prob: np.ndarray,
                     rule_score: np.ndarray, recent_intervals: int, dt_summary: pd.DataFrame | None,
                     dts: pd.DataFrame, dt_prob: pd.Series | None, true_ntl_consumer: pd.Series,
                     true_ntl_dt_unmetered: pd.Series | None = None) -> pd.DataFrame:
    """Unified lead table (consumer + network leads) with simulated-truth evaluation columns.

    ``true_ntl_consumer`` / ``true_ntl_dt_unmetered`` are ground truth used only to score a
    campaign (``is_hit``, ``true_recoverable_kwh``); they never influence ranking.
    """
    f = features.reindex(consumers.consumer_id)
    est = consumer_energy_at_stake(f, recent_intervals).to_numpy()
    c_leads = pd.DataFrame({
        "lead_id": consumers.consumer_id.to_numpy(), "lead_type": "consumer",
        "substation": consumers.substation.to_numpy(), "dt_id": consumers.dt_id.to_numpy(),
        "x_km": consumers.x_km.to_numpy(), "y_km": consumers.y_km.to_numpy(),
        "prob": np.asarray(prob, dtype=float), "est_kwh": est, "rule_score": np.asarray(rule_score, dtype=float),
        "true_recoverable_kwh": true_ntl_consumer.reindex(consumers.consumer_id).fillna(0.0).to_numpy(),
    })
    c_leads["is_hit"] = c_leads.true_recoverable_kwh > 1.0
    frames = [c_leads]
    if dt_summary is not None and len(dt_summary) and dt_prob is not None:
        s = dt_summary.set_index("node_id")
        explained = (c_leads.assign(e=c_leads.prob * c_leads.est_kwh).groupby("dt_id").e.sum())
        d = dts.set_index("dt_id").reindex(s.index)
        unexplained = (s.excess_residual_kwh - explained.reindex(s.index).fillna(0.0)).clip(lower=0)
        n_leads = pd.DataFrame({
            "lead_id": s.index.to_numpy(), "lead_type": "network", "substation": d.substation.to_numpy(),
            "dt_id": s.index.to_numpy(), "x_km": d.x_km.to_numpy(), "y_km": d.y_km.to_numpy(),
            "prob": dt_prob.reindex(s.index).fillna(0.0).to_numpy(), "est_kwh": unexplained.to_numpy(),
            "rule_score": -np.inf,
            "true_recoverable_kwh": (true_ntl_dt_unmetered.reindex(s.index).fillna(0.0).to_numpy()
                                     if true_ntl_dt_unmetered is not None else 0.0),
        })
        n_leads["is_hit"] = n_leads.true_recoverable_kwh > 1.0
        frames.append(n_leads)
    return pd.concat(frames, ignore_index=True)
