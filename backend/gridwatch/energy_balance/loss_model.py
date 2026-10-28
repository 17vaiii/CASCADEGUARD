"""Utility-side technical-loss estimate.

This is deliberately *not* the simulator's physics (the iterative feeder power flow).
It is a simplified one-pass analytic estimate that a utility could compute from its
network records and the energy it can see:

    P_k, Q_k   metered + imputed demand of DT k, Q_k = P_k * tan(phi_k), where tan(phi_k)
               is the energy-weighted value from consumer tariff-category power factors
    V          one-pass voltage-drop estimate:  dV ~= R*P + X*Q  (per unit) along the path
    loss_b     R_b * (P_b^2 + Q_b^2) / V_b^2     for each series branch (LV, DT, MV)
    core       rated DT no-load loss while the feeder is energised

Differences from the simulated "true" losses come from the single-pass voltage
approximation, the background loss-model error drawn per feeder, Scenario G and —
crucially — from any energy that consumer meters do not see (an unmetered load also
causes additional losses that this estimate cannot know about).
"""

from __future__ import annotations

import numpy as np

from ..simulation.topology import Topology

LOSS_MODEL_REL_SD = 0.15  # uncertainty attached to the estimate in the energy balance


class LossModel:
    def __init__(self, topo: Topology, tan_phi_dt: np.ndarray):
        self.topo = topo
        self.dt_ids = topo.dt_ids
        self.feeder_ids = topo.feeder_ids
        n_dt = len(self.dt_ids)
        self.tan_phi = np.asarray(tan_phi_dt, dtype=float)
        self.r_dt, self.x_dt = np.zeros(n_dt), np.zeros(n_dt)
        self.r_lv, self.x_lv = np.zeros(n_dt), np.zeros(n_dt)
        self.core_kw = np.zeros(n_dt)
        self.dt_feeder = np.zeros(n_dt, dtype=int)
        for k, dt_id in enumerate(self.dt_ids):
            dt = topo.dts[dt_id]
            tp = topo.branches[dt.trafo_branch].params
            self.r_dt[k] = tp["vkr_percent"] / 100.0 / tp["sn_mva"]
            self.x_dt[k] = np.sqrt(max(tp["vk_percent"] ** 2 - tp["vkr_percent"] ** 2, 0.0)) / 100.0 / tp["sn_mva"]
            lp = topo.branches[dt.lv_branch].params
            zb = topo.buses[dt.group_bus].vn_kv ** 2
            self.r_lv[k] = lp["r_ohm_per_km"] * lp["length_km"] / zb
            self.x_lv[k] = lp["x_ohm_per_km"] * lp["length_km"] / zb
            self.core_kw[k] = tp["pfe_kw"]
            self.dt_feeder[k] = self.feeder_ids.index(dt.feeder)
        # MV segments in feeder order: (feeder, r_pu, x_pu, downstream DT indices)
        self.mv_segments: list[tuple[int, float, float, np.ndarray]] = []
        self.dt_upstream_segments: dict[int, list[int]] = {k: [] for k in range(n_dt)}
        for f, fid in enumerate(self.feeder_ids):
            fd = topo.feeders[fid]
            for s, seg in enumerate(fd.mv_branches):
                p = topo.branches[seg].params
                zb = topo.buses[topo.branches[seg].to_bus].vn_kv ** 2
                downstream = np.array([self.dt_ids.index(d) for d in fd.dts[s:]])
                seg_idx = len(self.mv_segments)
                self.mv_segments.append((f, p["r_ohm_per_km"] * p["length_km"] / zb,
                                         p["x_ohm_per_km"] * p["length_km"] / zb, downstream))
                for k in downstream:
                    self.dt_upstream_segments[int(k)].append(seg_idx)

    def estimate(self, dt_load_kwh: np.ndarray, energised: np.ndarray) -> dict[str, np.ndarray]:
        """dt_load_kwh: [n_dt, W] metered + imputed consumer energy per DT per hour.
        energised: [n_f, W]. Returns estimated kWh per hour: lv [n_dt,W], dt [n_dt,W], mv [n_f,W]."""
        P = dt_load_kwh / 1000.0  # MW on a 1 MVA base == per unit
        Q = P * self.tan_phi[:, None]
        # Segment flows (ignoring losses) and one-pass voltage at each MV node.
        seg_p = [P[ds].sum(axis=0) for (_, _, _, ds) in self.mv_segments]
        seg_q = [Q[ds].sum(axis=0) for (_, _, _, ds) in self.mv_segments]
        seg_dv = [r * p + x * q for (_, r, x, _), p, q in zip(self.mv_segments, seg_p, seg_q)]
        v_mv = np.ones_like(P)
        for k, segs in self.dt_upstream_segments.items():
            for s in segs:
                v_mv[k] -= seg_dv[s]
        v_lv = v_mv - (self.r_dt[:, None] * P + self.x_dt[:, None] * Q) / v_mv
        v_grp = v_lv - (self.r_lv[:, None] * P + self.x_lv[:, None] * Q) / v_lv
        lv = self.r_lv[:, None] * (P**2 + Q**2) / v_grp**2
        p_dt, q_dt = P + lv, Q + self.x_lv[:, None] / np.maximum(self.r_lv[:, None], 1e-12) * lv
        on_dt = energised[self.dt_feeder]
        dt = self.r_dt[:, None] * (p_dt**2 + q_dt**2) / v_lv**2 + self.core_kw[:, None] / 1000.0
        mv = np.zeros((len(self.feeder_ids), P.shape[1]))
        for (f, r, _x, ds), sp, sq in zip(self.mv_segments, seg_p, seg_q):
            v_end = v_mv[ds[0]]
            mv[f] += r * (sp**2 + sq**2) / v_end**2
        return {"lv": lv * on_dt * 1000.0, "dt": dt * on_dt * 1000.0, "mv": mv * energised * 1000.0}
