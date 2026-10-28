"""Feature engineering.

All features are *causal*: features at evaluation time tau use only readings that had
arrived by tau (delayed readings are invisible until they arrive) and only intervals
up to tau. Windows end at tau: W24 = last 24 h, W72, W168, and PRE = the 168 h before W72.

Consumer-only features (what a consumer-meter analytics system sees):
    ratio_24/72/168      observed / expected energy over the window (available readings only)
    peer_ratio_72/168    ratio divided by the median ratio of peers (same feeder & category);
                         removes common-mode effects such as weather
    z_24                 standardised deviation of the 24 h total from expectation
    low_frac_72          share of hours below 50 % of expectation
    zero_frac_72         share of exact-zero readings (outage hours excluded)
    peak_ratio_72        ratio on the consumer's usual high-consumption hours
    offpeak_ratio_72     ratio on the remaining hours
    shift_ratio          ratio_72 / ratio over PRE (sudden-change indicator)
    completeness_24/168  received / expected readings
    corr_72              correlation of observed and expected hourly shape

Grid-context features (energy accounting of the boundaries containing the consumer):
    dt_ratio_24, dt_z_24, dt_ratio_168, dt_z_168            DT energy balance
    feeder_ratio_24, feeder_z_24, feeder_ratio_168          feeder energy balance
    deficit_to_dt_gap_168   consumer's net shortfall (kWh) / DT unexplained energy
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..energy_balance.balance import EnergyAccountant
from ..features.baseline import Baseline
from ..simulation.generator import SimulationData

CONSUMER_FEATURES = [
    "ratio_24", "ratio_72", "ratio_168", "peer_ratio_72", "peer_ratio_168", "z_24", "low_frac_72",
    "zero_frac_72", "peak_ratio_72", "offpeak_ratio_72", "shift_ratio", "completeness_24", "completeness_168",
    "corr_72",
]
GRID_FEATURES = [
    "dt_ratio_24", "dt_z_24", "dt_ratio_168", "dt_z_168", "feeder_ratio_24", "feeder_z_24", "feeder_ratio_168",
    "deficit_to_dt_gap_168",
]
COMBINED_FEATURES = CONSUMER_FEATURES + GRID_FEATURES
UNIT_FEATURES = [
    "ratio_24", "z_24", "ratio_72", "z_72", "ratio_168", "z_168", "coverage_24", "coverage_168",
    "input_gap_frac_24", "imputed_share_24", "frac_low_consumers", "min_peer_ratio_72",
    "deficit_to_gap_168", "deficit_share_168", "consumer_rule_hits",
]

FEATURE_DESCRIPTIONS = {
    "ratio_24": "Observed / expected consumption, last 24 h",
    "ratio_72": "Observed / expected consumption, last 72 h",
    "ratio_168": "Observed / expected consumption, last 7 days",
    "peer_ratio_72": "72 h ratio relative to peers on the same feeder and category",
    "peer_ratio_168": "7-day ratio relative to peers",
    "z_24": "Standardised deviation of last-24 h consumption",
    "low_frac_72": "Share of hours below 50 % of expected (72 h)",
    "zero_frac_72": "Share of zero readings (72 h)",
    "peak_ratio_72": "Observed / expected during usual high-consumption hours (72 h)",
    "offpeak_ratio_72": "Observed / expected during other hours (72 h)",
    "shift_ratio": "Last 72 h ratio / preceding 7-day ratio (sudden change)",
    "completeness_24": "Received / expected readings, last 24 h",
    "completeness_168": "Received / expected readings, last 7 days",
    "corr_72": "Correlation of observed and expected hourly shape (72 h)",
    "dt_ratio_24": "DT unexplained energy / DT input, last 24 h",
    "dt_z_24": "DT unexplained energy in standard deviations, last 24 h",
    "dt_ratio_168": "DT unexplained energy / DT input, last 7 days",
    "dt_z_168": "DT unexplained energy in standard deviations, last 7 days",
    "feeder_ratio_24": "Feeder unexplained energy / feeder input, last 24 h",
    "feeder_z_24": "Feeder unexplained energy in standard deviations, last 24 h",
    "feeder_ratio_168": "Feeder unexplained energy / feeder input, last 7 days",
    "deficit_to_dt_gap_168": "Consumer's net shortfall / DT unexplained energy (7 days)",
    "z_72": "Unexplained energy in standard deviations, last 72 h",
    "z_168": "Unexplained energy in standard deviations, last 7 days",
    "coverage_24": "Consumer-reading coverage inside the boundary, last 24 h",
    "coverage_168": "Consumer-reading coverage inside the boundary, last 7 days",
    "input_gap_frac_24": "Share of hours without an input-meter reading (24 h)",
    "imputed_share_24": "Imputed energy / input energy (24 h)",
    "frac_low_consumers": "Share of consumers with peer ratio < 0.7 (72 h)",
    "min_peer_ratio_72": "Lowest consumer peer ratio inside the boundary (72 h)",
    "deficit_to_gap_168": "Sum of consumer shortfalls / unexplained energy (7 days)",
    "deficit_share_168": "Sum of consumer shortfalls / input energy (7 days)",
    "consumer_rule_hits": "Consumers flagged by the consumer threshold rule",
}

LOOKBACK = 240


@dataclass
class RuleConfig:
    """Thresholds of the transparent rule-based baseline (configurable)."""

    consumer_shortfall: float = 0.35  # flag if peer-adjusted 72 h consumption is >= 35 % below expected
    min_completeness: float = 0.80  # ... and at least 80 % of readings were received
    balance_ratio: float = 0.03  # flag a boundary if unexplained >= 3 % of input (24 h) ...
    balance_z: float = 2.0  # ... and >= 2 standard deviations
    combined_dt_z: float = 2.0  # combined rule: consumer flag AND DT imbalance >= 2 sigma (72 h)


def _ratio(num: np.ndarray, den: np.ndarray, default: float = 1.0) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 1e-9, num / den, default)


def _peer_normalise(ratio: np.ndarray, groups: np.ndarray, fallback_groups: np.ndarray) -> np.ndarray:
    out = np.empty_like(ratio)
    for g in np.unique(groups):
        m = groups == g
        ref = ratio[m] if m.sum() >= 4 else ratio[fallback_groups == fallback_groups[m][0]]
        med = np.median(ref)
        out[m] = ratio[m] / med if med > 1e-6 else ratio[m]
    return out


class FeatureBuilder:
    def __init__(self, data: SimulationData, baseline: Baseline, accountant: EnergyAccountant,
                 rules: RuleConfig | None = None):
        self.d, self.base, self.acc = data, baseline, accountant
        self.rules = rules or RuleConfig()
        cat_code = {c: i for i, c in enumerate(sorted(set(data.consumer_category)))}
        self.peer_group = data.consumer_feeder_idx * 10 + np.array([cat_code[c] for c in data.consumer_category])
        self.theft_dt = data.label_theft_dt()
        self.theft_feeder = data.label_theft_feeder()

    # ------------------------------------------------------------------------------------
    def at(self, tau: int) -> dict:
        """All features at evaluation time tau (absolute hour index)."""
        d, base, acc = self.d, self.base, self.acc
        a, b = tau - LOOKBACK + 1, tau + 1
        comp = acc.components(a, b, tau)
        W = comp.b - comp.a
        A = comp.c_avail
        O = comp.c_metered
        X = base.expected_kwh[:, comp.a:comp.b]
        S2 = base.expected_sd[:, comp.a:comp.b] ** 2
        PK = base.peak_mask[:, comp.a:comp.b]
        N = comp.c_need

        def win(h):  # slice of the last h hours inside the components window
            return slice(max(0, W - h), W)

        def wsum(arr, h, mask=None):
            s = win(h)
            m = A[:, s] if mask is None else (A[:, s] & mask[:, s])
            return np.where(m, arr[:, s], 0.0).sum(axis=1)

        f: dict[str, np.ndarray] = {}
        for h in (24, 72, 168):
            f[f"ratio_{h}"] = _ratio(wsum(O, h), wsum(X, h))
        pre = slice(max(0, W - 240), max(0, W - 72))
        pre_obs = np.where(A[:, pre], O[:, pre], 0).sum(axis=1)
        pre_exp = np.where(A[:, pre], X[:, pre], 0).sum(axis=1)
        f["peer_ratio_72"] = _peer_normalise(f["ratio_72"], self.peer_group, d.consumer_feeder_idx)
        f["peer_ratio_168"] = _peer_normalise(f["ratio_168"], self.peer_group, d.consumer_feeder_idx)
        f["z_24"] = _ratio(wsum(O, 24) - wsum(X, 24), np.sqrt(wsum(S2, 24)), 0.0)
        s72 = win(72)
        n72 = A[:, s72].sum(axis=1)
        f["low_frac_72"] = _ratio((A[:, s72] & (O[:, s72] < 0.5 * X[:, s72])).sum(axis=1), n72, 0.0)
        f["zero_frac_72"] = _ratio((A[:, s72] & (O[:, s72] <= 0.0)).sum(axis=1), n72, 0.0)
        f["peak_ratio_72"] = _ratio(wsum(O, 72, PK), wsum(X, 72, PK))
        f["offpeak_ratio_72"] = _ratio(wsum(O, 72, ~PK), wsum(X, 72, ~PK))
        f["shift_ratio"] = _ratio(f["ratio_72"], _ratio(pre_obs, pre_exp))
        for h in (24, 168):
            s = win(h)
            f[f"completeness_{h}"] = _ratio(A[:, s].sum(axis=1), N[:, s].sum(axis=1))
        o72 = np.where(A[:, s72], O[:, s72], np.nan)
        x72 = np.where(A[:, s72], X[:, s72], np.nan)
        om, xm = np.nanmean(o72, axis=1, keepdims=True), np.nanmean(x72, axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            cov = np.nanmean((o72 - om) * (x72 - xm), axis=1)
            corr = cov / (np.nanstd(o72, axis=1) * np.nanstd(x72, axis=1))
        f["corr_72"] = np.nan_to_num(corr, nan=0.0)

        # ---- boundary energy balances ------------------------------------------------
        hr_dt = acc.hourly(comp, "dt")
        hr_f = acc.hourly(comp, "feeder")
        dt_w = {h: acc.window_stats(comp, "dt", b - h, b, hr_dt) for h in (24, 72, 168)}
        f_w = {h: acc.window_stats(comp, "feeder", b - h, b, hr_f) for h in (24, 72, 168)}
        ci, fi = d.consumer_dt_idx, d.consumer_feeder_idx
        f["dt_ratio_24"], f["dt_z_24"] = dt_w[24]["ratio"][ci], dt_w[24]["z"][ci]
        f["dt_ratio_168"], f["dt_z_168"] = dt_w[168]["ratio"][ci], dt_w[168]["z"][ci]
        f["feeder_ratio_24"], f["feeder_z_24"] = f_w[24]["ratio"][fi], f_w[24]["z"][fi]
        f["feeder_ratio_168"] = f_w[168]["ratio"][fi]
        deficit = np.maximum(0.0, wsum(X, 168) - wsum(O, 168))
        gap = dt_w[168]["unexplained"][ci]
        floor = 0.01 * dt_w[168]["input"][ci] + 1e-6
        f["deficit_to_dt_gap_168"] = np.clip(deficit / np.maximum(gap, floor), 0.0, 5.0)

        cons = np.column_stack([f[k] for k in COMBINED_FEATURES])
        cons = np.nan_to_num(cons, nan=0.0, posinf=5.0, neginf=-5.0)
        # Evidence used only by the explanation engine (not model inputs).
        f["obs_72"], f["exp_72"] = wsum(O, 72), wsum(X, 72)
        f["peak_obs_72"], f["peak_exp_72"] = wsum(O, 72, PK), wsum(X, 72, PK)
        blocks = []  # daily observed/expected ratio for the last 10 whole 24 h blocks (newest first)
        for k in range(LOOKBACK // 24):
            sk = slice(W - 24 * (k + 1), W - 24 * k)
            blocks.append(_ratio(np.where(A[:, sk], O[:, sk], 0).sum(axis=1),
                                 np.where(A[:, sk], X[:, sk], 0).sum(axis=1)))
        below = np.column_stack(blocks) < 0.75
        f["days_below_75"] = np.where(below.all(axis=1), below.shape[1], np.argmin(below, axis=1))

        # ---- rule outputs ----------------------------------------------------------------
        r = self.rules
        shortfall = 1.0 - f["peer_ratio_72"]
        c72 =_ratio(A[:, s72].sum(axis=1), N[:, s72].sum(axis=1))
        ok = c72 >= r.min_completeness
        consumer_rule = np.where(ok, shortfall / r.consumer_shortfall, 0.0)
        balance_rule_f = np.minimum(f_w[24]["ratio"] / r.balance_ratio, f_w[24]["z"] / r.balance_z)
        balance_rule_dt = np.minimum(dt_w[24]["ratio"] / r.balance_ratio, dt_w[24]["z"] / r.balance_z)
        combined_rule = np.minimum(consumer_rule, dt_w[72]["z"][ci] / r.combined_dt_z)
        dflt = RuleConfig()
        default_rule_flag = (c72 >= dflt.min_completeness) & (shortfall >= dflt.consumer_shortfall)

        # ---- unit features (DT and feeder) ---------------------------------------------
        units = {}
        for kind, w, member_idx in (("dt", dt_w, ci), ("feeder", f_w, fi)):
            n_u = len(w[24]["input"])
            low = (f["peer_ratio_72"] < 0.7) & ok
            frac_low = np.bincount(member_idx, weights=low, minlength=n_u) / np.maximum(
                np.bincount(member_idx, minlength=n_u), 1)
            min_pr = np.full(n_u, 5.0)
            np.minimum.at(min_pr, member_idx, np.where(ok, f["peer_ratio_72"], 5.0))
            sum_def = np.bincount(member_idx, weights=deficit, minlength=n_u)
            # Model input: always uses the *default* rule so user-tuned thresholds cannot shift it.
            hits = np.bincount(member_idx, weights=default_rule_flag, minlength=n_u)
            u168 = w[168]["unexplained"]
            in168 = w[168]["input"]
            uf = {
                "ratio_24": w[24]["ratio"], "z_24": w[24]["z"], "ratio_72": w[72]["ratio"], "z_72": w[72]["z"],
                "ratio_168": w[168]["ratio"], "z_168": w[168]["z"], "coverage_24": w[24]["coverage"],
                "coverage_168": w[168]["coverage"],
                "input_gap_frac_24": 1.0 - _ratio(w[24]["hours_used"], w[24]["hours_in_time"]),
                "imputed_share_24": _ratio(w[24]["imputed"], w[24]["input"], 0.0),
                "frac_low_consumers": frac_low, "min_peer_ratio_72": min_pr,
                "deficit_to_gap_168": np.clip(sum_def / np.maximum(u168, 0.01 * in168 + 1e-6), 0, 5),
                "deficit_share_168": _ratio(sum_def, in168, 0.0), "consumer_rule_hits": hits,
            }
            hr = hr_f if kind == "feeder" else hr_dt
            sig_days = []  # consecutive whole days (newest first) with unexplained energy >= 2 sigma
            for k in range(LOOKBACK // 24):
                wk = acc.window_stats(comp, kind, b - 24 * (k + 1), b - 24 * k, hr)
                sig_days.append(wk["z"] >= r.balance_z)
            sd = np.column_stack(sig_days)
            units[kind] = {
                "X": np.nan_to_num(np.column_stack([uf[k] for k in UNIT_FEATURES]), nan=0.0, posinf=5.0, neginf=-5.0),
                "raw": uf,
                "balance": {h: w[h] for h in (24, 72, 168)},
                "balance_rule": balance_rule_f if kind == "feeder" else balance_rule_dt,
                "days_imbalanced": np.where(sd.all(axis=1), sd.shape[1], np.argmin(sd, axis=1)),
                "sum_deficit_168": sum_def,
            }

        return {
            "tau": tau,
            "consumer_X": cons,
            "consumer_raw": f,
            "consumer_rule": consumer_rule,
            "combined_rule": combined_rule,
            "units": units,
            "deficit_168": deficit,
            "completeness_72": c72,
        }

    # ------------------------------------------------------------------------------------
    def labels_at(self, tau: int) -> dict[str, np.ndarray]:
        """Window labels: 1 if a theft-like event is active for >= 12 of the 24 h ending at tau,
        0 if active for none of them, -1 (ambiguous, excluded from training/metrics) otherwise."""
        s = slice(tau - 23, tau + 1)

        def lab(active: np.ndarray) -> np.ndarray:
            n = active[:, s].sum(axis=1)
            return np.where(n >= 12, 1, np.where(n == 0, 0, -1))

        d = self.d
        return {
            "consumer": lab(d.label_theft_consumer),
            "dt": lab(self.theft_dt),
            "feeder": lab(self.theft_feeder),
            "consumer_benign": d.label_benign_change[:, s].any(axis=1),
            "consumer_fault": d.label_data_fault[:, s].any(axis=1),
        }

    def daily_taus(self) -> list[int]:
        return [self.d.h0 + 24 * k + 23 for k in range(self.d.n_steps // 24)]

    def frame(self, taus: list[int], run_id: str = "") -> dict[str, pd.DataFrame]:
        """Stacked feature tables (consumer, dt, feeder) for several evaluation times."""
        parts = [self.tables(self.at(tau), run_id) for tau in taus]
        return {k: pd.concat([p[k] for p in parts], ignore_index=True) for k in ("consumer", "dt", "feeder")}

    def tables(self, ft: dict, run_id: str = "") -> dict[str, pd.DataFrame]:
        """Feature tables for one evaluation time from the output of `at`."""
        d = self.d
        tau = ft["tau"]
        lb = self.labels_at(tau)
        dfc = pd.DataFrame(ft["consumer_X"], columns=COMBINED_FEATURES)
        dfc["consumer_rule"] = ft["consumer_rule"]
        dfc["combined_rule"] = ft["combined_rule"]
        dfc["feeder_balance_rule"] = ft["units"]["feeder"]["balance_rule"][d.consumer_feeder_idx]
        dfc["unit"] = d.consumer_ids
        dfc["feeder"] = np.array(d.feeder_ids)[d.consumer_feeder_idx]
        dfc["dt"] = np.array(d.dt_ids)[d.consumer_dt_idx]
        dfc["category"] = d.consumer_category
        dfc["label"] = lb["consumer"]
        dfc["benign"] = lb["consumer_benign"]
        dfc["fault"] = lb["consumer_fault"]
        dfc["tau"] = tau
        dfc["run"] = run_id
        out = {"consumer": dfc}
        for kind, ids in (("dt", d.dt_ids), ("feeder", d.feeder_ids)):
            u = ft["units"][kind]
            df = pd.DataFrame(u["X"], columns=UNIT_FEATURES)
            df["balance_rule"] = u["balance_rule"]
            df["unit"] = ids
            df["label"] = lb[kind]
            df["tau"] = tau
            df["run"] = run_id
            out[kind] = df
        return out
