# OWNER: P5 | NEEDS: P1 | STATUS: ACTIVE
"""R9 / P5-2: OR-Tools minimal mitigation (load shedding, tie/hydro redispatch, line switching).

At the post-contingency operating point, AC finite-difference sensitivities give the change of
every in-service line's loading and of the required hydro output per unit of each control:

* ``tie``   - raise (or lower) the state-grid import; Sharavathi hydro moves the other way (H2),
* ``shed:<bus>`` - shed real load at a substation,
* ``open:<line>`` - open a line (binary, effect taken as one whole step).

A mixed-integer program then minimises shedding / redispatch / switching cost plus a per-action
penalty (fewest actions, PRD R9) subject to every line below the loading target and hydro inside
its H2/H3 bounds. The linear model is only a proposal: :mod:`cascadeguard.mitigation.verifier`
re-simulates it with the P1 engine and re-linearises if it fails.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandapower as pp

from cascadeguard.mitigation.network import (
    LOAD_BUSES, Actions, Event, OperatingState, post_contingency,
)


@dataclass
class Sensitivity:
    controls: list[str]
    lines: list[int]
    loading0: np.ndarray                 # [n_lines] current loading %
    S: np.ndarray                        # [n_lines, n_controls] d loading per unit control
    H: np.ndarray                        # [n_controls] d hydro MW per unit control
    hydro0: float
    lower: np.ndarray                    # control bounds (units: MW or 0/1)
    upper: np.ndarray
    kinds: list[str] = field(default_factory=list)
    n_power_flows: int = 0


def _solve(net: pp.pandapowerNet) -> bool:
    try:
        pp.runpp(net, algorithm="nr", init="results", max_iteration=50, numba=False)
        return True
    except Exception:
        try:
            pp.runpp(net, algorithm="nr", init="dc", max_iteration=50, numba=False)
            return True
        except Exception:
            return False


def sensitivities(state: OperatingState, event: Event, actions: Actions, max_switch: int = 6,
                  step: float = 10.0) -> Sensitivity | None:
    """AC finite-difference sensitivities at the post-contingency (+ current actions) point."""
    import copy
    base, info = post_contingency(state, event, actions)
    if not info["converged"]:
        return None
    lines = [int(i) for i in base.line.index[base.line.in_service & base.res_line.loading_percent.notna()]]
    load0 = base.res_line.loading_percent.reindex(lines).to_numpy()
    hydro0 = float(base.res_ext_grid.p_mw.sum())
    cfg = state.cfg
    controls, kinds, lo, hi, cols, hcol = [], [], [], [], [], []
    n_pf = 1

    def measure(net: pp.pandapowerNet) -> tuple[np.ndarray, float] | None:
        if not _solve(net):
            return None
        return net.res_line.loading_percent.reindex(lines).fillna(0.0).to_numpy(), float(net.res_ext_grid.p_mw.sum())

    tie_avail = not event.tie_loss and base.sgen.at[state.tie_idx, "in_service"]
    if tie_avail:
        tie_now = float(base.sgen.at[state.tie_idx, "p_mw"])
        room_up = cfg["grid_tie"]["max_import_mw"] - tie_now
        room_dn = tie_now - cfg["grid_tie"]["min_import_mw"]
        if room_up > 0.5 or room_dn > 0.5:
            net = copy.deepcopy(base)
            d = step if room_up >= step else -step
            net.sgen.at[state.tie_idx, "p_mw"] = tie_now + d
            m = measure(net)
            n_pf += 1
            if m is not None:
                controls.append("tie"); kinds.append("tie")
                cols.append((m[0] - load0) / d); hcol.append((m[1] - hydro0) / d)
                lo.append(-room_dn); hi.append(room_up)
    for bus in LOAD_BUSES:
        b = int(base["name_to_idx"][bus])
        rows = base.load.index[(base.load.bus == b) & base.load.in_service]
        p = float(base.load.p_mw[rows].sum())
        if p <= 0.5:
            continue
        net = copy.deepcopy(base)
        d = min(step, p)
        for r in rows:
            frac = float(net.load.at[r, "p_mw"]) / p
            net.load.at[r, "q_mvar"] *= 1 - d / p
            net.load.at[r, "p_mw"] -= d * frac
        m = measure(net)
        n_pf += 1
        if m is not None:
            controls.append(f"shed:{bus}"); kinds.append("shed")
            cols.append((m[0] - load0) / d); hcol.append((m[1] - hydro0) / d)
            lo.append(0.0); hi.append(p)
    # Switching candidates: in-service lines adjacent to the most loaded section.
    if max_switch > 0 and len(lines):
        worst = lines[int(np.argmax(load0))]
        sec = state.net["line_section"].get(worst, 0)
        cand = [l for l in lines if l != worst and abs(state.net["line_section"].get(l, -99) - sec) <= 2][:max_switch]
        from cascadeguard.sim.islanding import detect_islands, island_has_generation
        for l in cand:
            net = copy.deepcopy(base)
            net.line.at[l, "in_service"] = False
            # Never propose a switch that cuts load off from every source.
            loaded = set(net.load.bus[net.load.in_service & (net.load.p_mw > 0)].astype(int))
            if any(not island_has_generation(net, isl) and isl & loaded for isl in detect_islands(net)):
                continue
            m = measure(net)
            n_pf += 1
            if m is not None:
                controls.append(f"open:{l}"); kinds.append("switch")
                eff = m[0] - load0
                eff[lines.index(l)] = -load0[lines.index(l)]          # the opened line itself drops out
                cols.append(eff); hcol.append(m[1] - hydro0)
                lo.append(0.0); hi.append(1.0)
    if not controls:
        return Sensitivity([], lines, load0, np.zeros((len(lines), 0)), np.zeros(0), hydro0,
                           np.zeros(0), np.zeros(0), [], n_pf)
    return Sensitivity(controls, lines, load0, np.column_stack(cols), np.asarray(hcol), hydro0,
                       np.asarray(lo), np.asarray(hi), kinds, n_pf)


def solve_milp(sens: Sensitivity, state: OperatingState, target_pct: float,
               hint: dict[str, float] | None = None) -> dict[str, Any]:
    """Minimum-cost incremental actions. Returns ``{status, delta: {control: value}, objective, time_s}``."""
    from ortools.linear_solver import pywraplp
    cfg = state.cfg
    costs, opt = cfg["costs"], cfg["optimizer"]
    t0 = time.perf_counter()
    solver = pywraplp.Solver.CreateSolver(opt.get("solver", "SCIP"))
    if solver is None:
        solver = pywraplp.Solver.CreateSolver("CBC")
    solver.SetTimeLimit(int(float(opt["time_limit_s"]) * 1000))
    u, y, terms = {}, {}, []
    tie_up, tie_dn = None, None
    for k, (name, kind) in enumerate(zip(sens.controls, sens.kinds)):
        if kind == "switch":
            u[name] = solver.IntVar(0, 1, name)
            y[name] = u[name]
            terms.append((costs["switch"] + costs["per_action"]) * u[name])
            continue
        if kind == "tie":
            up = solver.NumVar(0, max(sens.upper[k], 0.0), "tie_up")
            dn = solver.NumVar(0, max(-sens.lower[k], 0.0), "tie_dn")
            tie_up, tie_dn = up, dn
            u[name] = up - dn
            y[name] = solver.BoolVar("y_tie")
            big = max(sens.upper[k], -sens.lower[k], 1.0)
            solver.Add(up + dn <= big * y[name])
            terms.append(costs["tie_per_mw"] * (up + dn) + costs["per_action"] * y[name])
            continue
        v = solver.NumVar(0, sens.upper[k], name)
        u[name] = v
        y[name] = solver.BoolVar(f"y_{name}")
        solver.Add(v <= max(sens.upper[k], 1.0) * y[name])
        terms.append(costs["shed_per_mw"] * v + costs["per_action"] * y[name])
    for i in range(len(sens.lines)):
        expr = sum(sens.S[i, k] * u[name] for k, name in enumerate(sens.controls))
        solver.Add(sens.loading0[i] + expr <= max(target_pct, 0.0))
    hydro_expr = sens.hydro0 + sum(sens.H[k] * u[name] for k, name in enumerate(sens.controls))
    solver.Add(hydro_expr <= state.hydro.max_mw)
    solver.Add(hydro_expr >= state.hydro.min_mw)
    solver.Minimize(sum(terms) if terms else 0)
    if hint:
        hv, hval = [], []
        for name, val in hint.items():
            if name == "tie" and tie_up is not None and tie_dn is not None:
                v = float(val)
                if v > 0:
                    hv.append(tie_up)
                    hval.append(v)
                    hv.append(tie_dn)
                    hval.append(0.0)
                elif v < 0:
                    hv.append(tie_up)
                    hval.append(0.0)
                    hv.append(tie_dn)
                    hval.append(-v)
                else:
                    hv.append(tie_up)
                    hval.append(0.0)
                    hv.append(tie_dn)
                    hval.append(0.0)
                continue
            var = u.get(name)
            if var is not None and hasattr(var, "solution_value"):
                hv.append(var)
                hval.append(float(val))
        if hv:
            solver.SetHint(hv, hval)
    status = solver.Solve()
    elapsed = time.perf_counter() - t0
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return {"status": "infeasible", "delta": {}, "objective": None, "time_s": elapsed}
    delta = {name: float(var.solution_value()) for name, var in u.items()}
    return {"status": "optimal" if status == pywraplp.Solver.OPTIMAL else "feasible",
            "delta": delta, "objective": float(solver.Objective().Value()), "time_s": elapsed}


def apply_delta(actions: Actions, delta: dict[str, float], tol: float = 0.05) -> Actions:
    """Combine current actions with an incremental MILP solution."""
    new = Actions(actions.tie_delta_mw, dict(actions.shed_mw), list(actions.open_lines))
    for name, val in delta.items():
        if name == "tie" and abs(val) > tol:
            new.tie_delta_mw += val
        elif name.startswith("shed:") and val > tol:
            bus = name.split(":", 1)[1]
            new.shed_mw[bus] = new.shed_mw.get(bus, 0.0) + val
        elif name.startswith("open:") and val > 0.5:
            new.open_lines.append(int(name.split(":", 1)[1]))
    return new
