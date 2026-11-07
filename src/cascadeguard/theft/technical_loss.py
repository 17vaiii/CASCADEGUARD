# OWNER: P4 | NEEDS: P1 | STATUS: ACTIVE
"""T1 / P4-2: technical (physical) loss estimation from power-flow models.

Two levels:

* **Distribution feeders.** Each 11 kV feeder is built as a pandapower radial model
  (trunk segments -> 11/0.433 kV distribution transformers -> aggregated LV line -> load).
  pandapower is run at several loading levels and a quadratic loss curve
  ``loss_kw = a + b*P + c*P^2`` is fitted against the feeder-head input ``P``
  (``a`` ~ transformer iron loss, ``c`` ~ I^2R). The curve is then evaluated on every
  metering interval, which is far faster than one power flow per interval.
* **Transmission corridor.** Per-section I^2R losses come directly from the P1 corridor
  model (``cascadeguard.grid.corridor_model``) after an AC power flow.

All parameters are assumptions from ``configs/theft/models.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pandapower as pp

from cascadeguard.theft import load_config


@dataclass
class FeederSpec:
    """Electrical description of one radial 11 kV feeder."""

    feeder_id: str
    segment_km: list[float]            # trunk length before each DT (source -> DT0, DT0 -> DT1, ...)
    dt_ratings_kva: list[float]
    dt_ids: list[str] = field(default_factory=list)
    vn_kv: float = 11.0
    r_ohm_per_km: float = 0.55
    x_ohm_per_km: float = 0.35
    c_nf_per_km: float = 10.0
    max_i_ka: float = 0.20
    power_factor: float = 0.92
    lv_r_ohm_per_km: float = 0.30
    lv_x_ohm_per_km: float = 0.08
    lv_km: float = 0.25
    dt_loss_kw: dict[str, list[float]] = field(default_factory=dict)

    @property
    def n_dts(self) -> int:
        return len(self.dt_ratings_kva)

    def dt_loss_params(self, rating_kva: float) -> tuple[float, float]:
        """(no-load kW, full-load copper kW) for a DT rating."""
        key = str(int(rating_kva))
        if key in self.dt_loss_kw:
            no_load, copper = self.dt_loss_kw[key]
            return float(no_load), float(copper)
        # Fallback: ~0.25 % iron and ~1.3 % copper loss of rating (assumed).
        return 0.0025 * rating_kva, 0.013 * rating_kva

    @classmethod
    def from_config(cls, feeder_id: str, segment_km: list[float], dt_ratings_kva: list[float],
                    dt_ids: list[str] | None = None, config: dict[str, Any] | None = None) -> "FeederSpec":
        cfg = (config or load_config())["feeder_electrical"]
        return cls(
            feeder_id=feeder_id, segment_km=list(segment_km), dt_ratings_kva=list(dt_ratings_kva),
            dt_ids=list(dt_ids or [f"{feeder_id}_DT{i}" for i in range(len(dt_ratings_kva))]),
            vn_kv=float(cfg["vn_kv"]), r_ohm_per_km=float(cfg["r_ohm_per_km"]),
            x_ohm_per_km=float(cfg["x_ohm_per_km"]), c_nf_per_km=float(cfg["c_nf_per_km"]),
            max_i_ka=float(cfg["max_i_ka"]), power_factor=float(cfg["power_factor"]),
            lv_r_ohm_per_km=float(cfg["lv_r_ohm_per_km"]), lv_x_ohm_per_km=float(cfg["lv_x_ohm_per_km"]),
            lv_km=float(cfg["lv_km"]), dt_loss_kw={str(k): v for k, v in cfg["dt_loss_kw"].items()},
        )


# ---------------------------------------------------------------------------
# pandapower feeder model
# ---------------------------------------------------------------------------

def build_feeder_net(spec: FeederSpec, dt_load_kw: np.ndarray | list[float]) -> pp.pandapowerNet:
    """Build the pandapower model of a feeder with the given real load behind each DT (kW)."""
    loads = np.asarray(dt_load_kw, dtype=float)
    if loads.shape != (spec.n_dts,):
        raise ValueError(f"expected {spec.n_dts} DT loads, got shape {loads.shape}")
    net = pp.create_empty_network(name=f"feeder_{spec.feeder_id}")
    source = pp.create_bus(net, vn_kv=spec.vn_kv, name=f"{spec.feeder_id}_SRC")
    pp.create_ext_grid(net, source, vm_pu=1.0, name="SUBSTATION_11KV")
    tan_phi = np.tan(np.arccos(spec.power_factor))
    upstream = source
    for i, (seg, kva, p_kw) in enumerate(zip(spec.segment_km, spec.dt_ratings_kva, loads)):
        hv = pp.create_bus(net, vn_kv=spec.vn_kv, name=f"{spec.dt_ids[i]}_HV")
        pp.create_line_from_parameters(
            net, upstream, hv, length_km=float(seg), r_ohm_per_km=spec.r_ohm_per_km,
            x_ohm_per_km=spec.x_ohm_per_km, c_nf_per_km=spec.c_nf_per_km, max_i_ka=spec.max_i_ka,
            name=f"{spec.feeder_id}_TRUNK{i}")
        lv = pp.create_bus(net, vn_kv=0.433, name=f"{spec.dt_ids[i]}_LV")
        no_load, copper = spec.dt_loss_params(kva)
        pp.create_transformer_from_parameters(
            net, hv, lv, sn_mva=kva / 1000.0, vn_hv_kv=spec.vn_kv, vn_lv_kv=0.433,
            vkr_percent=copper / kva * 100.0, vk_percent=4.5, pfe_kw=no_load, i0_percent=0.4,
            name=spec.dt_ids[i])
        load_bus = pp.create_bus(net, vn_kv=0.433, name=f"{spec.dt_ids[i]}_LOAD")
        pp.create_line_from_parameters(
            net, lv, load_bus, length_km=spec.lv_km, r_ohm_per_km=spec.lv_r_ohm_per_km,
            x_ohm_per_km=spec.lv_x_ohm_per_km, c_nf_per_km=0.0, max_i_ka=2.0,
            name=f"{spec.dt_ids[i]}_LV")
        pp.create_load(net, load_bus, p_mw=p_kw / 1000.0, q_mvar=p_kw * tan_phi / 1000.0,
                       name=f"LOAD_{spec.dt_ids[i]}")
        upstream = hv
    return net


def run_feeder_power_flow(spec: FeederSpec, dt_load_kw: np.ndarray | list[float],
                          net: pp.pandapowerNet | None = None) -> dict[str, Any]:
    """AC power flow of one feeder state. Returns head input, total and per-element losses (kW).

    Pass a ``net`` from :func:`build_feeder_net` to reuse it (only the loads are updated);
    building a pandapower network is several times slower than solving it.
    """
    loads = np.asarray(dt_load_kw, dtype=float)
    if net is None:
        net = build_feeder_net(spec, loads)
    else:
        tan_phi = np.tan(np.arccos(spec.power_factor))
        net.load["p_mw"] = loads / 1000.0
        net.load["q_mvar"] = loads * tan_phi / 1000.0
    pp.runpp(net, algorithm="nr", numba=False)
    input_kw = float(net.res_ext_grid.p_mw.sum() * 1000.0)
    load_kw = float(net.load.p_mw.sum() * 1000.0)
    trunk = net.line.name.str.contains("_TRUNK")
    dt_side = (net.res_trafo.pl_mw.to_numpy() + net.res_line.pl_mw[~trunk].to_numpy()) * 1000.0
    return {
        "input_kw": input_kw,
        "load_kw": load_kw,
        "loss_kw": input_kw - load_kw,
        "trunk_loss_kw": float(net.res_line.pl_mw[trunk].sum() * 1000.0),
        "dt_loss_kw": dt_side,   # transformer + LV line loss, per DT
        "min_vm_pu": float(net.res_bus.vm_pu.min()),
        "max_trunk_loading_pct": float(net.res_line.loading_percent[trunk].max()),
    }


# ---------------------------------------------------------------------------
# Fast analytic losses (used by the simulator for the *true* state) and fitted curves
# ---------------------------------------------------------------------------

def analytic_losses(spec: FeederSpec, dt_load_kw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised I^2R + iron losses for loads of shape [n_dts, T] (kW).

    Returns ``(trunk_loss_kw [T], dt_loss_kw [n_dts, T])``. Uses nominal voltage, so it is a
    close (validated in tests) but simpler companion of the pandapower model.
    """
    p = np.atleast_2d(np.asarray(dt_load_kw, dtype=float))
    pf = spec.power_factor
    v_hv, v_lv = spec.vn_kv, 0.433
    dt_loss = np.empty_like(p)
    for i, kva in enumerate(spec.dt_ratings_kva):
        no_load, copper = spec.dt_loss_params(kva)
        s = p[i] / pf
        lv_loss = s**2 * spec.lv_r_ohm_per_km * spec.lv_km / (v_lv**2 * 1000.0)
        dt_loss[i] = no_load + copper * (s / kva) ** 2 + lv_loss
    dt_input = p + dt_loss
    downstream = np.cumsum(dt_input[::-1], axis=0)[::-1]       # flow on segment before DT i
    seg_r = np.asarray(spec.segment_km)[:, None] * spec.r_ohm_per_km
    trunk = (seg_r * (downstream / pf) ** 2 / (v_hv**2 * 1000.0)).sum(axis=0)
    return trunk, dt_loss


@dataclass
class LossCurve:
    """Quadratic technical-loss curve ``loss = a + b*P + c*P^2`` (kW in, kW out)."""

    a: float
    b: float
    c: float
    p_min_kw: float = 0.0
    p_max_kw: float = float("inf")
    max_rel_error: float = 0.0          # worst relative error of the fit on its pandapower points

    def predict(self, p_kw: np.ndarray | float) -> np.ndarray:
        p = np.asarray(p_kw, dtype=float)
        return np.maximum(0.0, self.a + self.b * p + self.c * p**2)

    def as_dict(self) -> dict[str, float]:
        return {"a": self.a, "b": self.b, "c": self.c, "p_min_kw": self.p_min_kw,
                "p_max_kw": self.p_max_kw, "max_rel_error": self.max_rel_error}


def _fit(p: np.ndarray, loss: np.ndarray) -> LossCurve:
    # Weight by 1/loss so the fit minimises *relative* error across light and heavy loading.
    c, b, a = np.polyfit(p, loss, deg=2, w=1.0 / np.maximum(loss, 1e-6))
    pred = a + b * p + c * p**2
    rel = float(np.max(np.abs(pred - loss) / np.maximum(loss, 1e-6)))
    return LossCurve(float(a), float(b), float(c), float(p.min()), float(p.max()), rel)


def fit_feeder_loss_curves(spec: FeederSpec, nominal_dt_kw: np.ndarray,
                           scales: list[float] | None = None) -> dict[str, Any]:
    """Fit the feeder-head and per-DT loss curves from pandapower runs.

    ``nominal_dt_kw`` is the typical load split across DTs; the feeder is solved at each
    multiple in ``scales``. Returns ``{"feeder": LossCurve, "dt": [LossCurve, ...], "points": df}``.
    """
    scales = scales or load_config()["feeder_electrical"]["fit_scales"]
    nominal = np.asarray(nominal_dt_kw, dtype=float)
    net = build_feeder_net(spec, nominal)
    rows = []
    dt_points: list[list[tuple[float, float]]] = [[] for _ in range(spec.n_dts)]
    for s in scales:
        res = run_feeder_power_flow(spec, nominal * float(s), net=net)
        rows.append({"scale": s, **{k: v for k, v in res.items() if k != "dt_loss_kw"}})
        for i in range(spec.n_dts):
            dt_points[i].append((nominal[i] * s, float(res["dt_loss_kw"][i])))
    points = pd.DataFrame(rows)
    feeder_curve = _fit(points.input_kw.to_numpy(), points.loss_kw.to_numpy())
    dt_curves = []
    for pts in dt_points:
        arr = np.asarray(pts)
        dt_curves.append(_fit(arr[:, 0], arr[:, 1]))
    # Trunk-loss correction: pandapower (real voltage drop) vs nominal-voltage analytic I^2R.
    nominal_res = run_feeder_power_flow(spec, nominal, net=net)
    analytic_trunk, _ = analytic_losses(spec, nominal[:, None])
    trunk_factor = float(nominal_res["trunk_loss_kw"] / max(float(analytic_trunk[0]), 1e-9))
    return {"feeder": feeder_curve, "dt": dt_curves, "points": points, "trunk_factor": trunk_factor}


def true_feeder_losses(spec: FeederSpec, curves: dict[str, Any], dt_load_kw: np.ndarray
                       ) -> tuple[np.ndarray, np.ndarray]:
    """Physically distributed losses for actual per-DT loads [n_dts, T] (simulator ground truth).

    DT + LV losses use each DT's pandapower-fitted curve on its *own* load; trunk loss uses
    the segment-wise I^2R with the pandapower voltage-drop correction. Unlike the estimator,
    this sees where the load (including hidden load) actually sits on the feeder.
    """
    p = np.atleast_2d(np.asarray(dt_load_kw, dtype=float))
    dt_loss = np.vstack([curves["dt"][i].predict(p[i]) for i in range(spec.n_dts)])
    pf = spec.power_factor
    dt_input = p + dt_loss
    downstream = np.cumsum(dt_input[::-1], axis=0)[::-1]
    seg_r = np.asarray(spec.segment_km)[:, None] * spec.r_ohm_per_km
    trunk = (seg_r * (downstream / pf) ** 2 / (spec.vn_kv**2 * 1000.0)).sum(axis=0)
    return trunk * float(curves.get("trunk_factor", 1.0)), dt_loss


# ---------------------------------------------------------------------------
# Transmission corridor losses (P1 model, read-only use)
# ---------------------------------------------------------------------------

def corridor_line_losses(net: pp.pandapowerNet) -> pd.DataFrame:
    """Per-section technical loss on the solved P1 corridor model (both circuits summed)."""
    if net.res_line is None or net.res_line.empty:
        pp.runpp(net, algorithm="nr", init="dc", numba=False)
    section = net.get("line_section", {})
    section_km = net.get("section_km", {})
    df = pd.DataFrame({
        "line_idx": net.line.index,
        "name": net.line.name.values,
        "section": [section.get(int(i), int(i)) for i in net.line.index],
        "loss_mw": net.res_line.pl_mw.values,
        "loading_pct": net.res_line.loading_percent.values,
    })
    out = df.groupby("section", as_index=False).agg(loss_mw=("loss_mw", "sum"),
                                                     max_loading_pct=("loading_pct", "max"))
    out["km_from"] = [section_km.get(s, (np.nan, np.nan))[0] for s in out.section]
    out["km_to"] = [section_km.get(s, (np.nan, np.nan))[1] for s in out.section]
    return out


def corridor_loss_summary(net: pp.pandapowerNet) -> dict[str, float]:
    """Total corridor technical loss (MW) and as % of delivered generation."""
    if net.res_line is None or net.res_line.empty:
        pp.runpp(net, algorithm="nr", init="dc", numba=False)
    loss = float(net.res_line.pl_mw.sum())
    gen = float(net.res_ext_grid.p_mw.sum() + (net.res_sgen.p_mw.sum() if len(net.sgen) else 0.0))
    return {"transmission_loss_mw": loss, "generation_mw": gen,
            "transmission_loss_pct": 100.0 * loss / max(gen, 1e-9)}
