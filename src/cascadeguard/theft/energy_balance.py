# OWNER: P4 | NEEDS: P2 | STATUS: ACTIVE
"""T2 / P4-3: energy-balance analysis at feeder and distribution-transformer level.

For every metered node (feeder head, metered DT) and interval::

    residual = measured input - sum(consumer metered energy below it) - expected technical loss

where the technical loss comes from the T1 power-flow-fitted curve evaluated on the measured
input. The residual is the *suspected* non-technical loss (NTL). Because a feeder always has
some unexplained remainder (meter noise, model error), the anomaly signal is the *change* of
the residual against the node's own reference (history) period, expressed as a z-score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from cascadeguard.theft.feeder_sim import DistributionDataset


@dataclass
class BalanceResult:
    """Per-interval and daily balance for one node level (``feeder`` or ``dt``)."""

    level: str
    node_ids: list[str]
    input_kwh: np.ndarray        # [N, T]
    metered_kwh: np.ndarray      # [N, T] sum of consumer meters below the node
    tech_loss_kwh: np.ndarray    # [N, T] estimated technical loss
    residual_kwh: np.ndarray     # [N, T]
    daily: pd.DataFrame          # node_id, date, day, input/metered/tech/residual kWh, residual_pct
    summary: pd.DataFrame        # node_id, hist/recent residual %, change, z, flagged, residual_kwh_recent


def _aggregate_consumers(ds: DistributionDataset, key: str, node_ids: list[str]) -> np.ndarray:
    index = {n: i for i, n in enumerate(node_ids)}
    rows = ds.consumers[key].map(index).to_numpy()
    out = np.zeros((len(node_ids), ds.n_periods))
    np.add.at(out, rows, ds.metered_imputed())
    return out


def _daily_frame(level: str, node_ids: list[str], ds: DistributionDataset, inp: np.ndarray,
                 met: np.ndarray, tech: np.ndarray, res: np.ndarray) -> pd.DataFrame:
    per_day = int(round(24 / ds.interval_hours))
    n_days = ds.n_periods // per_day
    shape = (len(node_ids), n_days, per_day)

    def daily(a: np.ndarray) -> np.ndarray:
        return a[:, :n_days * per_day].reshape(shape).sum(axis=2)

    d_in, d_met, d_tech, d_res = daily(inp), daily(met), daily(tech), daily(res)
    dates = ds.timestamps[::per_day][:n_days].date
    frame = pd.DataFrame({
        "level": level,
        "node_id": np.repeat(node_ids, n_days),
        "day": np.tile(np.arange(n_days), len(node_ids)),
        "date": np.tile(dates, len(node_ids)),
        "input_kwh": d_in.ravel(), "metered_kwh": d_met.ravel(),
        "tech_loss_kwh": d_tech.ravel(), "residual_kwh": d_res.ravel(),
    })
    frame["residual_pct"] = 100.0 * frame.residual_kwh / frame.input_kwh.clip(lower=1e-9)
    frame["tech_loss_pct"] = 100.0 * frame.tech_loss_kwh / frame.input_kwh.clip(lower=1e-9)
    return frame


def _summarise(daily: pd.DataFrame, history_days: int, flag_z: float) -> pd.DataFrame:
    hist = daily[daily.day < history_days].groupby("node_id").residual_pct.agg(["mean", "std"])
    recent = daily[daily.day >= history_days]
    rec = recent.groupby("node_id").agg(recent_pct=("residual_pct", "mean"),
                                        residual_kwh_recent=("residual_kwh", "sum"),
                                        input_kwh_recent=("input_kwh", "sum"))
    # 7-day peak of the residual in the scoring window catches events that start late.
    peak = (recent.sort_values("day").groupby("node_id").residual_pct
            .apply(lambda s: s.rolling(7, min_periods=3).mean().max()).rename("peak7_pct"))
    out = hist.join(rec).join(peak).reset_index()
    out = out.rename(columns={"mean": "hist_pct", "std": "hist_std"})
    out["hist_std"] = out.hist_std.fillna(0.0).clip(lower=0.05)
    out["change_pct"] = out.recent_pct - out.hist_pct
    out["peak_change_pct"] = out.peak7_pct - out.hist_pct
    out["z"] = out.peak_change_pct / out.hist_std
    out["flagged"] = out.z >= flag_z
    excess = (out.recent_pct - out.hist_pct).clip(lower=0) / 100.0 * out.input_kwh_recent
    out["excess_residual_kwh"] = excess
    return out


def feeder_balance(ds: DistributionDataset, flag_z: float = 3.0) -> BalanceResult:
    """Feeder-head energy balance (every feeder has a head meter)."""
    ids = ds.feeders.feeder_id.tolist()
    inp = ds.feeder_input_kwh.astype(np.float64)
    met = _aggregate_consumers(ds, "feeder_id", ids)
    tech = np.vstack([ds.curves[f]["feeder"].predict(inp[i] / ds.interval_hours) * ds.interval_hours
                      for i, f in enumerate(ids)])
    res = inp - met - tech
    daily = _daily_frame("feeder", ids, ds, inp, met, tech, res)
    history_days = ds.history_end // int(round(24 / ds.interval_hours))
    return BalanceResult("feeder", ids, inp, met, tech, res, daily, _summarise(daily, history_days, flag_z))


def dt_balance(ds: DistributionDataset, flag_z: float = 3.0) -> BalanceResult:
    """DT-level balance, for DTs that carry an energy meter (others are NaN / not reported)."""
    metered_dts = ds.dts[ds.dts.metered]
    ids = metered_dts.dt_id.tolist()
    rows = metered_dts.index.to_numpy()
    inp = ds.dt_input_kwh[rows].astype(np.float64)
    met = _aggregate_consumers(ds, "dt_id", ds.dts.dt_id.tolist())[rows]
    tech = np.zeros_like(inp)
    for j, (fid, pos) in enumerate(zip(metered_dts.feeder_id, metered_dts.position)):
        curve = ds.curves[fid]["dt"][int(pos)]
        tech[j] = curve.predict(inp[j] / ds.interval_hours) * ds.interval_hours
    res = inp - met - tech
    daily = _daily_frame("dt", ids, ds, inp, met, tech, res)
    history_days = ds.history_end // int(round(24 / ds.interval_hours))
    return BalanceResult("dt", ids, inp, met, tech, res, daily, _summarise(daily, history_days, flag_z))


def true_ntl_by_node(ds: DistributionDataset, key: str) -> pd.Series:
    """Ground-truth NTL kWh in the scoring window per feeder/DT (for evaluation only)."""
    ntl = ds.ntl_kwh[:, ds.history_end:].sum(axis=1)
    return pd.Series(ntl, index=ds.consumers[key].values).groupby(level=0).sum()


def localisation_accuracy(summary: pd.DataFrame, truth_ntl: pd.Series, top_n: int,
                          min_ntl_kwh: float = 1.0) -> dict[str, Any]:
    """PRD metric: share of feeders (or DTs) with injected theft ranked in the top N by z."""
    ranked = summary.sort_values("z", ascending=False).node_id.tolist()
    theft_nodes = set(truth_ntl[truth_ntl > min_ntl_kwh].index) & set(ranked)
    top = set(ranked[:top_n])
    flagged = set(summary.node_id[summary.flagged])
    tp = len(flagged & theft_nodes)
    return {
        "n_nodes": len(ranked), "n_theft_nodes": len(theft_nodes), "top_n": top_n,
        "theft_nodes_in_top_n": len(top & theft_nodes),
        "top_n_precision": len(top & theft_nodes) / max(len(top), 1),
        "top_n_recall": len(top & theft_nodes) / max(min(len(theft_nodes), top_n), 1),
        "flagged": len(flagged), "flag_precision": tp / max(len(flagged), 1),
        "flag_recall": tp / max(len(theft_nodes), 1),
        "spearman_z_vs_true_ntl": float(pd.Series(summary.set_index("node_id").z)
                                        .corr(truth_ntl.reindex(summary.node_id).fillna(0)
                                              .set_axis(summary.node_id), method="spearman")),
    }


def loss_split(ds: DistributionDataset, balance: BalanceResult, window: str = "recent") -> dict[str, float]:
    """Technical vs non-technical split of feeder input energy (estimated and true)."""
    sl = slice(ds.history_end, None) if window == "recent" else slice(0, ds.history_end)
    inp = float(balance.input_kwh[:, sl].sum())
    met = float(balance.metered_kwh[:, sl].sum())
    tech_est = float(balance.tech_loss_kwh[:, sl].sum())
    res_est = float(balance.residual_kwh[:, sl].sum())
    tech_true = float(ds.true_dt_loss_kwh[:, sl].sum() + ds.true_trunk_loss_kwh[:, sl].sum())
    ntl_true = float(ds.ntl_kwh[:, sl].sum())
    pct = lambda x: 100.0 * x / max(inp, 1e-9)  # noqa: E731
    return {
        "window": window, "input_mwh": inp / 1e3, "metered_mwh": met / 1e3,
        "technical_loss_pct_est": pct(tech_est), "technical_loss_pct_true": pct(tech_true),
        "ntl_pct_est": pct(res_est), "ntl_pct_true": pct(ntl_true),
        "technical_loss_est_error_pct_points": pct(tech_est) - pct(tech_true),
    }


def residual_heatmap(balance: BalanceResult, freq_days: int = 7) -> pd.DataFrame:
    """Node x week matrix of residual % (PRD §7.4 feeder heatmap of unexplained loss)."""
    d = balance.daily.copy()
    d["week"] = d.day // freq_days
    agg = d.groupby(["node_id", "week"]).agg(res=("residual_kwh", "sum"), inp=("input_kwh", "sum"))
    agg["residual_pct"] = 100.0 * agg.res / agg.inp.clip(lower=1e-9)
    return agg.residual_pct.unstack("week")


def ntl_ratio_by_substation(ds: DistributionDataset, balance: BalanceResult) -> pd.DataFrame:
    """Estimated and true NTL as a fraction of *metered* energy per corridor substation (T9 input).

    Estimated ratio = positive change of the feeder residual vs history (so the always-present
    model/noise remainder is not counted as hidden load) divided by metered energy.
    """
    s = balance.summary.set_index("node_id")
    feeders = ds.feeders.set_index("feeder_id")
    sl = slice(ds.history_end, None)
    met = pd.Series(balance.metered_kwh[:, sl].sum(axis=1), index=balance.node_ids)
    true = pd.Series(ds.ntl_kwh[:, sl].sum(axis=1), index=ds.consumers.feeder_id.values).groupby(level=0).sum()
    df = pd.DataFrame({"substation": feeders.substation.reindex(balance.node_ids).values,
                       "metered_kwh": met.values,
                       "est_hidden_kwh": s.excess_residual_kwh.reindex(balance.node_ids).values,
                       "true_hidden_kwh": true.reindex(balance.node_ids).fillna(0.0).values})
    out = df.groupby("substation").sum()
    out["est_ntl_ratio"] = out.est_hidden_kwh / out.metered_kwh
    out["true_ntl_ratio"] = out.true_hidden_kwh / out.metered_kwh
    return out.reset_index()
