"""Full-network AC power flow (pandapower) for one displayed time step.

The snapshot includes the meshed 220 kV network, the receiving station, the 66 kV
system and every 11 kV feeder, with the *true* simulated demand of the step (including
any simulated unmetered load). It supplies the line flows, loadings and voltages drawn
on the network canvas. Energy accounting does not use these numbers: it uses metered
hourly energy, as a utility would.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from . import profiles as P
from .topology import Topology

log = logging.getLogger("gridwatch.snapshot")
# pandapower warns on every solve that the optional numba accelerator is missing; the solve
# itself is correct (just slower), so keep the server log readable.
logging.getLogger("pandapower").setLevel(logging.ERROR)

try:  # pandapower is optional at import time so the rest of the app still works without it
    import pandapower as pp

    HAVE_PANDAPOWER = True
except Exception:  # pragma: no cover
    pp = None
    HAVE_PANDAPOWER = False


def build_net(topo: Topology, distribution_only: bool = False):
    """Create a pandapower net from the topology. Returns (net, bus_idx, line_idx, trafo_idx, load_idx)."""
    net = pp.create_empty_network(name="GridWatch illustrative network", sn_mva=1.0)
    bus_idx: dict[str, int] = {}
    keep = None
    if distribution_only:
        keep = {"DSS11"} | {b.id for b in topo.buses.values() if b.feeder is not None}
    for b in topo.buses.values():
        if keep is not None and b.id not in keep:
            continue
        bus_idx[b.id] = pp.create_bus(net, vn_kv=b.vn_kv, name=b.id)
    line_idx: dict[str, int] = {}
    trafo_idx: dict[str, int] = {}
    for br in topo.branches.values():
        if br.from_bus not in bus_idx or br.to_bus not in bus_idx:
            continue
        p = br.params
        if br.kind == "line":
            if br.std_type:
                line_idx[br.id] = pp.create_line(net, bus_idx[br.from_bus], bus_idx[br.to_bus], p["length_km"],
                                                 std_type=br.std_type, parallel=br.parallel, name=br.id)
            else:
                line_idx[br.id] = pp.create_line_from_parameters(
                    net, bus_idx[br.from_bus], bus_idx[br.to_bus], p["length_km"], r_ohm_per_km=p["r_ohm_per_km"],
                    x_ohm_per_km=p["x_ohm_per_km"], c_nf_per_km=p.get("c_nf_per_km", 0.0), max_i_ka=p["max_i_ka"],
                    parallel=br.parallel, name=br.id)
        else:
            trafo_idx[br.id] = pp.create_transformer_from_parameters(
                net, bus_idx[br.from_bus], bus_idx[br.to_bus], sn_mva=p["sn_mva"], vn_hv_kv=p["vn_hv_kv"],
                vn_lv_kv=p["vn_lv_kv"], vkr_percent=p["vkr_percent"], vk_percent=p["vk_percent"],
                pfe_kw=p["pfe_kw"], i0_percent=p["i0_percent"], parallel=br.parallel, name=br.id)
    load_idx: dict[str, int] = {}
    for dt in topo.dts.values():
        load_idx[dt.id] = pp.create_load(net, bus_idx[dt.group_bus], p_mw=0.0, q_mvar=0.0, name=f"{dt.id} demand")
    if distribution_only:
        pp.create_ext_grid(net, bus_idx["DSS11"], vm_pu=1.0, name="DSS11 slack")
    else:
        pp.create_ext_grid(net, bus_idx["GRID220"], vm_pu=1.0, name="Interconnected grid")
        pp.create_gen(net, bus_idx["HYD220"], p_mw=400.0, vm_pu=1.0, name="Hydro source (illustrative dispatch)")
        load_idx["OTHER66"] = pp.create_load(net, bus_idx["OTHER66"], p_mw=0.0, q_mvar=0.0, name="Other 66 kV load")
    return net, bus_idx, line_idx, trafo_idx, load_idx


class GridSnapshotModel:
    def __init__(self, topo: Topology):
        if not HAVE_PANDAPOWER:
            raise RuntimeError("pandapower is not installed")
        self.topo = topo
        self.net, self.bus_idx, self.line_idx, self.trafo_idx, self.load_idx = build_net(topo)
        self._solved = False
        self._last_topology: tuple | None = None

    def solve(self, hour_of_day: int, dow: int, dt_p_mw: dict[str, float], dt_q_mvar: dict[str, float],
              energised: dict[str, bool]) -> dict:
        net, topo = self.net, self.topo
        for dt_id, li in self.load_idx.items():
            if dt_id == "OTHER66":
                p = P.other_66kv_load_mw(hour_of_day, dow)
                net.load.at[li, "p_mw"] = p
                net.load.at[li, "q_mvar"] = p * np.tan(np.arccos(0.95))
            else:
                net.load.at[li, "p_mw"] = dt_p_mw.get(dt_id, 0.0)
                net.load.at[li, "q_mvar"] = dt_q_mvar.get(dt_id, 0.0)
        gen_mw = P.hydro_dispatch_mw(hour_of_day)
        net.gen.at[0, "p_mw"] = gen_mw
        for fid, fd in topo.feeders.items():
            net.line.at[self.line_idx[fd.head_branch], "in_service"] = bool(energised.get(fid, True))
        t0 = time.perf_counter()
        # Warm-start from the previous solution only if it converged with the same energised feeders;
        # an outage leaves NaN voltages on isolated buses, which must never seed the next solve.
        topology_key = tuple(sorted(energised.items()))
        warm = self._solved and topology_key == self._last_topology
        converged = False
        for init in (("results", "flat") if warm else ("auto", "flat")):
            try:
                pp.runpp(net, numba=False, calculate_voltage_angles=True, init=init)
                converged = True
                break
            except Exception as exc:  # retried with a flat start, then reported to the UI
                log.warning("power flow (init=%s) did not converge: %s", init, exc)
        self._solved = converged
        self._last_topology = topology_key if converged else None
        solve_ms = (time.perf_counter() - t0) * 1000.0
        if not converged:
            return {"converged": False, "solver": "pandapower Newton-Raphson", "solve_ms": solve_ms}
        buses = {}
        for bid, bi in self.bus_idx.items():
            r = net.res_bus.loc[bi]
            vm = float(r.vm_pu) if np.isfinite(r.vm_pu) else None
            buses[bid] = {"vm_pu": vm, "va_degree": float(r.va_degree) if np.isfinite(r.va_degree) else None,
                          "p_mw": float(r.p_mw) if np.isfinite(r.p_mw) else 0.0}
        branches = {}
        for bid, li in self.line_idx.items():
            r = net.res_line.loc[li]
            branches[bid] = {"p_from_mw": _f(r.p_from_mw), "q_from_mvar": _f(r.q_from_mvar), "p_to_mw": _f(r.p_to_mw),
                             "loss_mw": _f(r.pl_mw), "loading_pct": _f(r.loading_percent), "i_ka": _f(r.i_ka),
                             "in_service": bool(net.line.at[li, "in_service"])}
        for bid, ti in self.trafo_idx.items():
            r = net.res_trafo.loc[ti]
            branches[bid] = {"p_from_mw": _f(r.p_hv_mw), "q_from_mvar": _f(r.q_hv_mvar), "p_to_mw": _f(r.p_lv_mw),
                             "loss_mw": _f(r.pl_mw), "loading_pct": _f(r.loading_percent), "i_ka": _f(r.i_hv_ka),
                             "in_service": True}
        return {
            "converged": True, "solver": "pandapower Newton-Raphson (AC)", "solve_ms": round(solve_ms, 1),
            "buses": buses, "branches": branches,
            "slack_p_mw": _f(net.res_ext_grid.p_mw.iloc[0]), "gen_p_mw": _f(net.res_gen.p_mw.iloc[0]),
            "other_66kv_load_mw": float(net.load.at[self.load_idx["OTHER66"], "p_mw"]),
            "total_loss_mw": float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()),
        }


def _f(x) -> float:
    x = float(x)
    return x if np.isfinite(x) else 0.0
