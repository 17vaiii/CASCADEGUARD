# OWNER: P4 | NEEDS: P1 | STATUS: ACTIVE
"""T8 / P4-12 (stretch): HT-line tapping detection on the 220 kV corridor.

Uses the P1 corridor model as the physics reference. SCADA measurements exist only at the
substations marked ``metered`` in ``configs/grids/corridor_v0.yaml`` (SIRA_KBCROSS is not):

* generation P/Q at Sharavathi, bus voltage magnitude at each metered substation,
* real/reactive flow entering and leaving each metered substation, and its load P/Q.

Method:

1. **Expected state** - solve the corridor with the *measured* substation loads (the unmetered
   junction load is unknown, so its nominal value is used).
2. **Detection** - generalized likelihood ratio: how much of the weighted residual
   ``J = ||(m - m_expected) / sigma||^2`` one tap load explains (``J - min_k J_k``); the alarm
   threshold is calibrated on simulated normal operation for a target false-alarm rate.
3. **Localisation** - linear sensitivities of the measurements to a 1 MW load at every 10 km tap
   bus; the tap whose sensitivity best explains the residual (non-negative least squares
   magnitude) is the estimate.

An unmetered junction load deviation and a tap near that junction produce similar signatures,
which bounds achievable accuracy; results are reported honestly with that limitation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pandapower as pp

from cascadeguard.theft import load_config


def _base_net(season: str = "post_monsoon") -> pp.pandapowerNet:
    from cascadeguard.grid.corridor_model import build_corridor_network, load_corridor_config
    from cascadeguard.grid.seasons import apply_season, load_season_profiles
    net = build_corridor_network()
    apply_season(net, load_season_profiles()[season])
    cfg = load_corridor_config()
    net["metered_names"] = [b["id"] for b in cfg["buses"] if b.get("metered", True)]
    net["tap_names"] = [n for n in net["name_to_idx"] if n.startswith("TAP_")]
    net.load["base_p"] = net.load.p_mw.copy()
    net.load["base_q"] = net.load.q_mvar.copy()
    pp.create_load(net, bus=0, p_mw=0.0, q_mvar=0.0, name="TAP_THEFT")   # moved per case
    return net


def _measure(net: pp.pandapowerNet) -> np.ndarray:
    """SCADA measurement vector from a solved net (ordered, metered points only)."""
    idx = net["name_to_idx"]
    m = [float(net.res_ext_grid.p_mw.sum()), float(net.res_ext_grid.q_mvar.sum())]
    real_loads = net.load[net.load.name != "TAP_THEFT"]
    for name in net["metered_names"]:
        b = idx[name]
        m.append(float(net.res_bus.vm_pu.at[b]))
        into = net.line.to_bus == b
        out = net.line.from_bus == b
        m += [float(-net.res_line.p_to_mw[into].sum()), float(net.res_line.p_from_mw[out].sum()),
              float(-net.res_line.q_to_mvar[into].sum()), float(net.res_line.q_from_mvar[out].sum())]
        here = real_loads.bus == b
        m += [float(real_loads.p_mw[here].sum()), float(real_loads.q_mvar[here].sum())]
    return np.asarray(m)


FULL_SCALE = {"p": 300.0, "q": 100.0, "vm": 1.0}   # assumed CT/PT full-scale ratings (MW, MVAr, pu)


def _sigma(m: np.ndarray, metered: int, noise: dict[str, float]) -> np.ndarray:
    """Meter 1-sigma error: accuracy class x full-scale rating (not x reading, which explodes
    for reactive flows that pass through zero)."""
    kinds = ["p", "q"] + ["vm", "p", "p", "q", "q", "p", "q"] * metered
    return np.array([noise[k] / 100.0 * FULL_SCALE[k] for k in kinds])


class TapDetector:
    def __init__(self, season: str = "post_monsoon", config: dict[str, Any] | None = None):
        self.cfg = (config or load_config())["ht_tapping"]
        self.net = _base_net(season)
        self.unmetered = [n for n in ("SIRA_KBCROSS",) if n not in self.net["metered_names"]]
        self.threshold: float | None = None
        self._build_sensitivity()

    # -- physics ------------------------------------------------------------
    def _solve(self, loads_p: np.ndarray, loads_q: np.ndarray, tap: str | None = None,
               tap_mw: float = 0.0, pf: float = 0.95) -> np.ndarray:
        net = self.net
        real = net.load.name != "TAP_THEFT"
        net.load.loc[real, "p_mw"] = loads_p
        net.load.loc[real, "q_mvar"] = loads_q
        t = net.load.index[net.load.name == "TAP_THEFT"][0]
        net.load.at[t, "bus"] = net["name_to_idx"][tap] if tap else 0
        net.load.at[t, "p_mw"] = tap_mw if tap else 0.0
        net.load.at[t, "q_mvar"] = tap_mw * np.tan(np.arccos(pf)) if tap else 0.0
        pp.runpp(net, algorithm="nr", init="dc", numba=False)
        return _measure(net)

    def _expected(self, measured: np.ndarray) -> np.ndarray:
        """Solve with metered substation loads as measured, unmetered loads at nominal."""
        net = self.net
        real = net.load[net.load.name != "TAP_THEFT"]
        p, q = real.base_p.to_numpy().copy(), real.base_q.to_numpy().copy()
        names = {v: k for k, v in net["name_to_idx"].items()}
        for i, bus in enumerate(real.bus):
            name = names[int(bus)]
            if name in net["metered_names"]:
                k = net["metered_names"].index(name)
                p[i], q[i] = measured[2 + 7 * k + 5], measured[2 + 7 * k + 6]
        return self._solve(p, q)

    def _build_sensitivity(self) -> None:
        real = self.net.load[self.net.load.name != "TAP_THEFT"]
        p, q = real.base_p.to_numpy(), real.base_q.to_numpy()
        base = self._solve(p, q)
        self.sens = {tap: self._solve(p, q, tap, 1.0) - base for tap in self.net["tap_names"]}
        self.tap_km = {tap: float(tap.split("_")[1]) for tap in self.net["tap_names"]}
        # Pseudo-measurement uncertainty of unmetered loads, propagated through the model:
        # sigma_model = |dm/dP_unmetered| * std(P_unmetered) (uniform +-u -> std = u*P/sqrt 3).
        names = {v: k for k, v in self.net["name_to_idx"].items()}
        u = float(self.cfg["unmetered_load_uncertainty"])
        model_var = np.zeros_like(base)
        for i, bus in enumerate(real.bus):
            if names[int(bus)] in self.unmetered:
                dp, dq = p.copy(), q.copy()
                dp[i] *= 1.01
                dq[i] *= 1.01
                d = (self._solve(dp, dq) - base) / 0.01        # per 100 % change
                model_var += (d * u / np.sqrt(3)) ** 2
        self.model_sigma = np.sqrt(model_var)

    # -- inference ----------------------------------------------------------
    def analyse(self, measured: np.ndarray) -> dict[str, Any]:
        expected = self._expected(measured)
        meter = _sigma(measured, len(self.net["metered_names"]), self.cfg["noise_pct"])
        sigma = np.sqrt(meter**2 + self.model_sigma**2)
        r = (measured - expected) / sigma
        stat = float(np.sum(r**2))
        best = (np.inf, None, 0.0)
        for tap, s in self.sens.items():
            sw = s / sigma
            alpha = max(0.0, float(sw @ r / max(sw @ sw, 1e-12)))
            err = float(np.sum((r - alpha * sw) ** 2))
            if err < best[0]:
                best = (err, tap, alpha)
        err, tap, mw = best
        glr = stat - err          # generalized likelihood ratio: residual explained by one tap load
        return {"statistic": glr, "chi2": stat, "suspicious": bool(self.threshold is not None and glr > self.threshold),
                "est_tap": tap, "est_km": self.tap_km.get(tap), "est_mw": mw}

    # -- simulation for evaluation -------------------------------------------
    def simulate_case(self, rng: np.random.Generator, tap: str | None, tap_mw: float) -> np.ndarray:
        real = self.net.load[self.net.load.name != "TAP_THEFT"]
        names = {v: k for k, v in self.net["name_to_idx"].items()}
        factor = rng.uniform(0.9, 1.05, len(real))
        for i, bus in enumerate(real.bus):
            if names[int(bus)] in self.unmetered:
                u = float(self.cfg["unmetered_load_uncertainty"])
                factor[i] = rng.uniform(1 - u, 1 + u)
        m = self._solve(real.base_p.to_numpy() * factor, real.base_q.to_numpy() * factor, tap, tap_mw)
        sigma = _sigma(m, len(self.net["metered_names"]), self.cfg["noise_pct"])
        return m + rng.normal(0, 1, m.shape) * sigma

    def calibrate(self, n: int = 150, seed: int = 0) -> float:
        rng = np.random.default_rng(seed)
        stats = [self.analyse(self.simulate_case(rng, None, 0.0))["statistic"] for _ in range(n)]
        self.threshold = float(np.quantile(stats, 1 - float(self.cfg["false_alarm_rate"])))
        return self.threshold


def evaluate_tapping(season: str = "post_monsoon", config: dict[str, Any] | None = None,
                     seed: int = 42) -> dict[str, Any]:
    cfg = (config or load_config())
    det = TapDetector(season, cfg)
    det.calibrate(seed=seed + 1)
    tc = cfg["ht_tapping"]
    rng = np.random.default_rng(seed)
    rows = []
    taps = det.net["tap_names"]
    for _ in range(int(tc["n_cases"])):
        theft = rng.random() < float(tc["theft_share"])
        tap = str(rng.choice(taps)) if theft else None
        mw = float(rng.uniform(*tc["tap_mw"])) if theft else 0.0
        res = det.analyse(det.simulate_case(rng, tap, mw))
        rows.append({"theft": theft, "true_km": det.tap_km.get(tap) if tap else np.nan, "true_mw": mw, **res})
    df = pd.DataFrame(rows)
    th, no = df[df.theft], df[~df.theft]
    det_th = th[th.suspicious]
    err = (det_th.est_km - det_th.true_km).abs()
    by_mw = {}
    for lo, hi in ((2, 5), (5, 15), (15, 30.01)):
        part = th[(th.true_mw >= lo) & (th.true_mw < hi)]
        e = (part[part.suspicious].est_km - part[part.suspicious].true_km).abs()
        by_mw[f"{lo}-{int(hi)}MW"] = {"n": int(len(part)), "recall": float(part.suspicious.mean()) if len(part) else np.nan,
                                      "median_km_error": float(e.median()) if len(e) else np.nan}
    return {
        "season": season, "n_cases": int(len(df)), "threshold": det.threshold,
        "recall": float(th.suspicious.mean()), "false_alarm_rate": float(no.suspicious.mean()),
        "mae_km": float(err.mean()) if len(err) else np.nan, "median_km": float(err.median()) if len(err) else np.nan,
        "within_20km": float((err <= 20).mean()) if len(err) else np.nan,
        "mw_mae": float((det_th.est_mw - det_th.true_mw).abs().mean()) if len(det_th) else np.nan,
        "by_magnitude": by_mw, "cases": df,
    }
