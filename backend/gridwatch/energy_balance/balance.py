"""Energy-balance (energy-accounting) engine.

For a monitoring boundary (an 11 kV feeder or one DT's LV network) and hourly
intervals h in a window, using only data available at evaluation time tau:

    U = E_in - E_metered - E_imputed - L_est                                  [kWh]

    E_in       boundary input meter (feeder-head meter or DT meter)
    E_metered  consumer smart-meter readings received by tau
    E_imputed  expected-profile estimate for readings that are missing or still delayed
               (an explicitly modelled adjustment; zero during known outages)
    L_est      utility-side technical-loss estimate (see loss_model.py), optionally multiplied
               by a per-boundary calibration factor k fitted on the reference (history) period:
               k = sum(E_in - E_metered - E_imputed) / sum(L_raw) over the history, clipped to
               [0.5, 2.0]. Calibration removes persistent loss-model bias but would also absorb any
               non-technical loss already present during the reference period (documented limit).

Hours whose input-meter reading is missing are dropped from *both* sides so the terms
cover identical intervals. U is an investigation signal, not proof of theft: it also
contains meter error, loss-model error and imputation error, which is why a 1-sigma
uncertainty is propagated:

    sigma^2 = (b_in E_in)^2 + r_in^2 sum e_in,h^2                (input meter bias + random error)
            + sum_i [(b_c E_i)^2 + r_c^2 sum_h e_i,h^2]           (consumer meters, independent)
            + (0.15 L_est)^2                                       (loss-model uncertainty)
            + sum_i [sum_h sd_i,h^2 + (0.2 E_imputed,i)^2]         (imputation)

using nominal accuracy-class figures — the utility does not know the true meter errors.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..features.baseline import Baseline
from ..simulation.generator import METER_ERROR, SimulationData
from ..simulation.profiles import POWER_FACTOR
from .loss_model import LOSS_MODEL_REL_SD, LossModel

UNEXPLAINED_WARNING = "Unexplained energy imbalance is an investigation signal, not proof of electricity theft."
IMPUTATION_REL_SD = 0.2


@dataclass
class Components:
    """Hourly energy-accounting terms for all consumers, DTs and feeders over [a, b)."""

    a: int
    b: int
    tau: int
    c_metered: np.ndarray  # [C, W]
    c_imputed: np.ndarray  # [C, W]
    c_imp_var: np.ndarray  # [C, W]
    c_need: np.ndarray  # [C, W] bool: a reading is expected (in time, no known outage)
    c_avail: np.ndarray  # [C, W] bool: reading received by tau
    c_pending: np.ndarray  # [C, W] bool: missing now but will arrive later
    dt_input: np.ndarray  # [n_dt, W] DT meter, NaN where unavailable
    feeder_input: np.ndarray  # [n_f, W]
    loss_lv: np.ndarray  # [n_dt, W] estimated
    loss_dt: np.ndarray  # [n_dt, W]
    loss_mv: np.ndarray  # [n_f, W]
    outage: np.ndarray  # [n_f, W] known outage

    def sl(self, lo: int, hi: int) -> slice:
        return slice(max(lo, self.a) - self.a, min(hi, self.b) - self.a)


class EnergyAccountant:
    def __init__(self, data: SimulationData, baseline: Baseline):
        self.d = data
        self.base = baseline
        C = len(data.consumer_ids)
        n_dt, n_f = len(data.dt_ids), len(data.feeder_ids)
        self.dt_member = np.zeros((n_dt, C))
        self.dt_member[data.consumer_dt_idx, np.arange(C)] = 1.0
        self.f_member = np.zeros((n_f, C))
        self.f_member[data.consumer_feeder_idx, np.arange(C)] = 1.0
        self.dt_feeder = data.dt_feeder_idx()
        self.f_dt_member = np.zeros((n_f, n_dt))
        self.f_dt_member[self.dt_feeder, np.arange(n_dt)] = 1.0
        # Energy-weighted tan(phi) per DT from tariff-category power factors (planning assumption).
        tan_c = np.tan(np.arccos([POWER_FACTOR[c] for c in data.consumer_category]))
        e_hist = baseline.expected_kwh[:, : data.h0].sum(axis=1)
        tan_dt = (self.dt_member @ (e_hist * tan_c)) / np.maximum(self.dt_member @ e_hist, 1e-9)
        self.loss_model = LossModel(data.topo, tan_dt)
        self.k_dt = np.ones(n_dt)
        self.k_f = np.ones(n_f)
        if data.config.loss_calibration and data.h0 > 0:
            self._calibrate()

    def _calibrate(self) -> None:
        """Fit per-boundary loss-calibration factors on the reference (history) period."""
        h0 = self.d.h0
        comp = self.components(0, h0, h0 - 1)
        for kind in ("dt", "feeder"):
            hr = self.hourly(comp, kind)
            m = hr["_m"]
            gap = m["input"].sum(axis=1) - m["metered"].sum(axis=1) - m["imputed"].sum(axis=1)
            raw = m["loss_est"].sum(axis=1)
            k = np.clip(np.where(raw > 0, gap / np.maximum(raw, 1e-9), 1.0), 0.5, 2.0)
            if kind == "dt":
                self.k_dt = k
            else:
                self.k_f = k

    # ------------------------------------------------------------------------------------
    def components(self, a: int, b: int, tau: int) -> Components:
        d, base = self.d, self.base
        a, b = max(0, a), min(d.H, b)
        hrs = np.arange(a, b)
        in_time = hrs <= tau
        meter = d.meter_kwh[:, a:b]
        delay = d.arrival_delay[:, a:b]
        arrived = (hrs[None, :] + delay) <= tau
        outage_c = base.outage_known[d.consumer_feeder_idx][:, a:b]
        need = in_time[None, :] & ~outage_c
        avail = need & arrived & np.isfinite(meter)
        missing = need & ~avail
        pending = missing & np.isfinite(delay)
        c_metered = np.where(avail, meter, 0.0)
        c_imputed = np.where(missing, base.expected_kwh[:, a:b], 0.0)
        c_imp_var = np.where(missing, base.expected_sd[:, a:b] ** 2, 0.0)
        dt_input = np.where(in_time[None, :], d.dt_meter_kwh[:, a:b], np.nan)
        feeder_input = np.where(in_time[None, :], d.feeder_meter_kwh[:, a:b], np.nan)
        outage = base.outage_known[:, a:b] & in_time[None, :]
        energised = ~base.outage_known[:, a:b] & in_time[None, :]
        est = self.loss_model.estimate(self.dt_member @ (c_metered + c_imputed), energised)
        lf = d.loss_estimate_factor[:, a:b]
        return Components(
            a=a, b=b, tau=tau, c_metered=c_metered, c_imputed=c_imputed, c_imp_var=c_imp_var, c_need=need,
            c_avail=avail, c_pending=pending, dt_input=dt_input, feeder_input=feeder_input,
            loss_lv=est["lv"] * lf[self.dt_feeder], loss_dt=est["dt"] * lf[self.dt_feeder], loss_mv=est["mv"] * lf,
            outage=outage,
        )

    # ------------------------------------------------------------------------------------
    def hourly(self, comp: Components, kind: str) -> dict[str, np.ndarray]:
        """Hourly boundary terms for every unit of `kind` ('feeder' | 'dt'): arrays [n_units, W].
        Hours with no input reading are NaN in every term."""
        M = self.f_member if kind == "feeder" else self.dt_member
        metered = M @ comp.c_metered
        imputed = M @ comp.c_imputed
        if kind == "feeder":
            e_in = comp.feeder_input
            loss = self.k_f[:, None] * (self.f_dt_member @ (comp.loss_lv + comp.loss_dt) + comp.loss_mv)
            outage = comp.outage
        else:
            e_in = comp.dt_input
            loss = self.k_dt[:, None] * comp.loss_lv
            outage = comp.outage[self.dt_feeder]
        valid = np.isfinite(e_in)
        nan = lambda x: np.where(valid, x, np.nan)  # noqa: E731
        hr = {
            "input": nan(e_in), "metered": nan(metered), "imputed": nan(imputed), "loss_est": nan(loss),
            "unexplained": nan(e_in - metered - imputed - loss), "valid": valid, "outage": outage,
        }
        # Masked copies used by window_stats: unit-level terms and consumer-level terms restricted
        # to hours where the unit's input reading exists (so both sides cover the same hours).
        e0 = np.where(valid, np.nan_to_num(e_in), 0.0)
        unit_of_c = self.d.consumer_feeder_idx if kind == "feeder" else self.d.consumer_dt_idx
        vc = valid[unit_of_c]
        cm = np.where(vc, comp.c_metered, 0.0)
        hr["_m"] = {
            "input": e0, "input_sq": e0**2, "metered": np.where(valid, metered, 0.0),
            "imputed": np.where(valid, imputed, 0.0), "loss_est": np.where(valid, loss, 0.0),
            "valid": valid.astype(float), "outage": outage.astype(float),
            "c_met": cm, "c_met_sq": cm**2, "c_imp": np.where(vc, comp.c_imputed, 0.0),
            "c_imp_var": np.where(vc, comp.c_imp_var, 0.0), "c_need": (vc & comp.c_need).astype(float),
            "c_avail": (vc & comp.c_avail).astype(float), "c_pending": (vc & comp.c_pending).astype(float),
        }
        return hr

    def window_stats(self, comp: Components, kind: str, lo: int, hi: int,
                     hourly: dict[str, np.ndarray] | None = None) -> dict[str, np.ndarray]:
        """Energy balance over hours [lo, hi) (clipped to data available at comp.tau) for every
        unit of `kind`. Returns arrays [n_units]."""
        hr = hourly or self.hourly(comp, kind)
        s = comp.sl(lo, hi)
        m = hr["_m"]
        win = lambda key: m[key][:, s].sum(axis=1)  # noqa: E731
        M = self.f_member if kind == "feeder" else self.dt_member
        E_in, E_met, E_imp, L = win("input"), win("metered"), win("imputed"), win("loss_est")
        U = E_in - E_met - E_imp - L
        meter_kind = "feeder_head" if kind == "feeder" else "dt"
        b_in, r_in = METER_ERROR[meter_kind]["bias"], METER_ERROR[meter_kind]["random"]
        b_c, r_c = METER_ERROR["consumer"]["bias"], METER_ERROR["consumer"]["random"]
        var_in = (b_in * E_in) ** 2 + r_in**2 * win("input_sq")
        var_c = M @ ((b_c * win("c_met")) ** 2 + r_c**2 * win("c_met_sq"))
        var_l = (LOSS_MODEL_REL_SD * L) ** 2
        var_imp = M @ (win("c_imp_var") + (IMPUTATION_REL_SD * win("c_imp")) ** 2)
        sigma = np.sqrt(var_in + var_c + var_l + var_imp)
        need, avail, pending = M @ win("c_need"), M @ win("c_avail"), M @ win("c_pending")
        hours_in_time = max(0, min(hi, comp.tau + 1, comp.b) - max(lo, comp.a))
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(sigma > 0, U / sigma, 0.0)
            ratio = np.where(E_in > 0, U / E_in, 0.0)
            coverage = np.where(need > 0, avail / need, 1.0)
        return {
            "input": E_in, "metered": E_met, "imputed": E_imp, "loss_est": L, "unexplained": U, "ratio": ratio,
            "sigma": sigma, "z": z, "coverage": coverage, "need": need, "missing": need - avail, "pending": pending,
            "hours_used": win("valid"), "hours_in_time": np.full(len(E_in), hours_in_time),
            "outage_hours": win("outage"),
            "var_parts": np.stack([var_in, var_c, var_l, var_imp], axis=1),
        }

    # ------------------------------------------------------------------------------------
    def balance(self, kind: str, uid: str, a: int, b: int, tau: int) -> dict:
        """Window totals, uncertainty and data-quality status for one boundary (API payload)."""
        d = self.d
        idx = d.feeder_ids.index(uid) if kind == "feeder" else d.dt_ids.index(uid)
        comp = self.components(a, b, tau)
        hr = self.hourly(comp, kind)
        w = self.window_stats(comp, kind, a, b, hr)
        g = lambda k: float(w[k][idx])  # noqa: E731
        E_in, U = g("input"), g("unexplained")
        gaps = int(w["hours_in_time"][idx] - w["hours_used"][idx])
        cov = g("coverage")
        quality = "good" if cov >= 0.98 and gaps == 0 else "fair" if cov >= 0.90 and gaps <= 2 else "poor"
        vp = np.sqrt(w["var_parts"][idx])
        s = comp.sl(a, b)
        series = {k: [None if not np.isfinite(v) else round(float(v), 3) for v in hr[k][idx, s]]
                  for k in ("input", "metered", "imputed", "loss_est", "unexplained")}
        return {
            "boundary": {"kind": kind, "id": uid},
            "window": {"start_hour": comp.a, "end_hour": comp.b, "evaluated_at_hour": tau,
                       "hours_in_time": int(w["hours_in_time"][idx]), "hours_used": int(w["hours_used"][idx])},
            "input_kwh": E_in,
            "metered_kwh": g("metered"),
            "imputed_kwh": g("imputed"),
            "estimated_loss_kwh": g("loss_est"),
            "unexplained_kwh": U,
            "unexplained_pct_of_input": (100.0 * U / E_in) if E_in > 0 else None,
            "sigma_kwh": g("sigma"),
            "z_score": g("z"),
            "uncertainty_components_kwh": {"input_meter": float(vp[0]), "consumer_meters": float(vp[1]),
                                           "loss_model": float(vp[2]), "imputation": float(vp[3])},
            "data_quality": {
                "status": quality, "consumer_reading_coverage": cov, "readings_expected": int(g("need")),
                "readings_missing_or_pending": int(g("missing")), "readings_pending_delayed": int(g("pending")),
                "input_meter_gaps_h": gaps, "known_outage_hours": int(g("outage_hours")),
                "duplicates_removed_run_total": d.ingestion["duplicates_removed"],
            },
            "hourly": series,
            "warning": UNEXPLAINED_WARNING,
        }
