# OWNER: P5 | NEEDS: P1,P4 | STATUS: ACTIVE
"""Operating state, contingency events, remedial actions and simulator-verified outcomes.

The P1 corridor model is single-source (all power enters at Sharavathi). For mitigation P5 adds
one documented assumption: an **equivalent state-grid tie** at NELAMANGALA, modelled as a
controllable import (pandapower ``sgen``, PQ, not grid-forming) with an assumed limit. The
Sharavathi slack then represents the Linganamakki hydro units, whose output must stay inside
the H2/H3 bounds from :mod:`cascadeguard.mitigation.hydro_redispatch`.

``evaluate_outcome`` is the closed-loop check used by every strategy: actions are applied, an
uncontrolled under-frequency load shed (UFLS) is modelled if hydro cannot cover a generation
deficit, and P1's AC cascade engine (``simulate_cascade``) re-simulates the event.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandapower as pp

from cascadeguard.mitigation import load_config
from cascadeguard.mitigation.hydro_redispatch import HydroBounds, base_hydro_dispatch, hydro_bounds

LOAD_BUSES = ("SHIMOGA", "SIRA_KBCROSS", "NELAMANGALA", "PEENYA")


@dataclass
class Event:
    """A contingency: initial line trips and/or loss of the state-grid tie."""

    lines: list[int] = field(default_factory=list)
    tie_loss: bool = False

    def __post_init__(self) -> None:
        self.lines = [int(x) for x in self.lines]     # plain ints: labels, IDs and JSON stay clean
        self.tie_loss = bool(self.tie_loss)

    @property
    def label(self) -> str:
        parts = [f"N-{len(self.lines)} {self.lines}"] if self.lines else []
        if self.tie_loss:
            parts.append("tie loss")
        return " + ".join(parts) or "none"

    def as_dict(self) -> dict[str, Any]:
        return {"lines": list(self.lines), "tie_loss": self.tie_loss, "label": self.label}


@dataclass
class Actions:
    """Remedial actions. ``tie_delta_mw`` > 0 raises import (hydro ramps down), < 0 lowers it."""

    tie_delta_mw: float = 0.0
    shed_mw: dict[str, float] = field(default_factory=dict)
    open_lines: list[int] = field(default_factory=list)
    caps_off: list[str] = field(default_factory=list)       # capacitor banks switched out (voltage control)

    def count(self, tol: float = 0.5) -> int:
        return (int(abs(self.tie_delta_mw) > tol) + sum(v > tol for v in self.shed_mw.values())
                + len(self.open_lines) + len(self.caps_off))

    def total_shed(self) -> float:
        return float(sum(self.shed_mw.values()))

    def as_dict(self) -> dict[str, Any]:
        return {"tie_delta_mw": round(float(self.tie_delta_mw), 3),
                "shed_mw": {k: round(float(v), 3) for k, v in self.shed_mw.items() if v > 1e-6},
                "open_lines": [int(x) for x in self.open_lines], "caps_off": list(self.caps_off)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Actions":
        return cls(float(d.get("tie_delta_mw", 0.0)), dict(d.get("shed_mw", {})), list(d.get("open_lines", [])),
                   list(d.get("caps_off", [])))


@dataclass
class OperatingState:
    season: str
    net: pp.pandapowerNet              # solved pre-contingency state (with tie and any hidden load)
    tie_mw: float
    hydro: HydroBounds
    total_load_mw: float
    cfg: dict[str, Any]
    hidden_mw: float = 0.0
    label: str = "scada"

    @property
    def tie_idx(self) -> int:
        return int(self.net["tie_sgen_idx"])

    def bus(self, name: str) -> int:
        return int(self.net["name_to_idx"][name])


def build_state(season: str, hidden: list[dict[str, Any]] | None = None, config: dict[str, Any] | None = None,
                label: str = "scada") -> OperatingState:
    """Seasonal pre-contingency state: P1 corridor (+ optional P4 hidden load) + grid tie + base dispatch."""
    from cascadeguard.grid.seasons import load_season_profiles
    from cascadeguard.theft.hidden_load import corridor_state      # P4 helper (keeps metadata consistent)
    cfg = config or load_config()
    profile = load_season_profiles()[season]
    net = corridor_state(season, hidden)
    tie = cfg["grid_tie"]
    tie_bus = int(net["name_to_idx"][tie["bus"]])
    idx = pp.create_sgen(net, bus=tie_bus, p_mw=0.0, q_mvar=0.0, name="STATE_GRID_TIE")
    net["tie_sgen_idx"] = int(idx)
    pp.runpp(net, algorithm="nr", init="dc", numba=False)
    demand = float(net.res_ext_grid.p_mw.sum())                     # load + losses with no import
    hydro0 = base_hydro_dispatch(profile, demand, float(cfg["dispatch"].get("budget_use_fraction", 1.0)))
    tie_mw = float(np.clip(demand - hydro0, tie["min_import_mw"], tie["max_import_mw"]))
    for _ in range(3):                                              # losses shift with the import
        _set_tie(net, tie_mw, tie["power_factor"])
        pp.runpp(net, algorithm="nr", init="dc", numba=False)
        hydro_now = float(net.res_ext_grid.p_mw.sum())
        tie_mw = float(np.clip(tie_mw + (hydro_now - hydro0), tie["min_import_mw"], tie["max_import_mw"]))
    _set_tie(net, tie_mw, tie["power_factor"])
    pp.runpp(net, algorithm="nr", init="dc", numba=False)
    # Reactive schedule: with a large import the long corridor runs lightly loaded and P1's
    # always-on capacitor banks push voltages up (Ferranti). Switch banks out, highest voltage
    # first, until the pre-contingency state is inside the normal 1.05 pu limit.
    switched_out = []
    while float(net.res_bus.vm_pu.max()) > 1.05 + 1e-4:
        live = net.shunt[net.shunt.in_service]
        if live.empty:
            break
        worst = live.index[int(np.argmax(net.res_bus.vm_pu.reindex(live.bus).to_numpy()))]
        net.shunt.at[worst, "in_service"] = False
        switched_out.append(str(net.shunt.at[worst, "name"]))
        pp.runpp(net, algorithm="nr", init="dc", numba=False)
    net["capacitors_switched_out"] = switched_out
    hydro_base = float(net.res_ext_grid.p_mw.sum())
    bounds = hydro_bounds(profile, hydro_base, cfg)
    hidden_mw = float(sum(h["hidden_load_mw"] for h in hidden or []))
    return OperatingState(season, net, tie_mw, bounds, float(net.load.p_mw.sum()), cfg, hidden_mw, label)


def _set_tie(net: pp.pandapowerNet, p_mw: float, pf: float) -> None:
    i = int(net["tie_sgen_idx"])
    net.sgen.at[i, "p_mw"] = max(0.0, float(p_mw))
    net.sgen.at[i, "q_mvar"] = max(0.0, float(p_mw)) * np.tan(np.arccos(pf))


def _apply_shed(net: pp.pandapowerNet, bus_name: str, mw: float) -> float:
    """Reduce real (and proportionally reactive) load at a substation; returns MW actually shed."""
    bus = int(net["name_to_idx"][bus_name])
    rows = net.load.index[(net.load.bus == bus) & net.load.in_service]
    remaining = float(mw)
    for r in rows:
        p = float(net.load.at[r, "p_mw"])
        cut = min(p, remaining)
        if p > 0 and cut > 0:
            net.load.at[r, "q_mvar"] *= (p - cut) / p
            net.load.at[r, "p_mw"] = p - cut
            remaining -= cut
    return float(mw) - remaining


def prepare(state: OperatingState, event: Event, actions: Actions | None = None) -> tuple[pp.pandapowerNet, dict[str, float]]:
    """Pre-trip net with the event's tie loss and the actions applied (trips are applied later)."""
    cfg = state.cfg
    net = copy.deepcopy(state.net)
    actions = actions or Actions()
    applied: dict[str, float] = {"tie_mw": state.tie_mw, "shed_mw": 0.0}
    if event.tie_loss:
        _set_tie(net, 0.0, cfg["grid_tie"]["power_factor"])
        net.sgen.at[state.tie_idx, "in_service"] = False
        applied["tie_mw"] = 0.0
    else:
        tie = float(np.clip(state.tie_mw + actions.tie_delta_mw, cfg["grid_tie"]["min_import_mw"],
                            cfg["grid_tie"]["max_import_mw"]))
        _set_tie(net, tie, cfg["grid_tie"]["power_factor"])
        applied["tie_mw"] = tie
    for bus, mw in actions.shed_mw.items():
        applied["shed_mw"] += _apply_shed(net, bus, mw)
    for name in actions.caps_off:
        net.shunt.loc[net.shunt.name == name, "in_service"] = False
    return net, applied


def add_voltage_control(state: OperatingState, event: Event, actions: Actions, max_steps: int = 4) -> Actions:
    """If post-contingency voltages exceed the band (e.g. after shedding on a lightly loaded line),
    switch out in-service capacitor banks, highest voltage first, as an extra recorded action."""
    vmax = float(state.cfg["limits"]["vm_max_pu"])
    acts = Actions(actions.tie_delta_mw, dict(actions.shed_mw), list(actions.open_lines), list(actions.caps_off))
    for _ in range(max_steps):
        net, info = post_contingency(state, event, acts)
        if not info["converged"] or info.get("vm_max", 0.0) <= vmax:
            break
        live = net.shunt[net.shunt.in_service]
        if live.empty:
            break
        worst = live.index[int(np.argmax(net.res_bus.vm_pu.reindex(live.bus).fillna(0).to_numpy()))]
        acts.caps_off.append(str(net.shunt.at[worst, "name"]))
    return acts


def post_contingency(state: OperatingState, event: Event, actions: Actions | None = None
                     ) -> tuple[pp.pandapowerNet, dict[str, Any]]:
    """Solved state right after the event (+ actions), with unpowered islands shed (P1 rules)."""
    from cascadeguard.sim.islanding import detect_islands, island_has_generation, shed_island_loads
    net, applied = prepare(state, event, actions)
    for li in list(event.lines) + list((actions or Actions()).open_lines):
        net.line.at[int(li), "in_service"] = False
    island_shed = 0.0
    for isl in detect_islands(net):
        if not island_has_generation(net, isl):
            shed, _ = shed_island_loads(net, isl)
            island_shed += shed
    info: dict[str, Any] = {**applied, "island_shed_mw": island_shed, "converged": True}
    try:
        pp.runpp(net, algorithm="nr", init="dc", max_iteration=50, numba=False)
    except Exception:
        info["converged"] = False
        return net, info
    lines = net.line.in_service
    info["max_loading_pct"] = float(net.res_line.loading_percent[lines].max()) if lines.any() else 0.0
    energised = net.res_bus.vm_pu.notna()
    info["vm_min"] = float(net.res_bus.vm_pu[energised].min())
    info["vm_max"] = float(net.res_bus.vm_pu[energised].max())
    info["hydro_mw"] = float(net.res_ext_grid.p_mw.sum())
    return net, info


def evaluate_outcome(state: OperatingState, event: Event, actions: Actions | None = None) -> dict[str, Any]:
    """Closed-loop verification with P1's cascade engine. Returns losses and a ``verified`` flag."""
    from cascadeguard.sim.cascade_engine import simulate_cascade
    cfg = state.cfg
    lim = cfg["limits"]
    actions = actions or Actions()
    if actions.count() > 0:          # an operator plan includes routine voltage control
        actions = add_voltage_control(state, event, actions)
    post, info = post_contingency(state, event, actions)
    ufls = 0.0
    if info["converged"] and info.get("hydro_mw", 0.0) > state.hydro.max_mw + 0.5:
        # Generation deficit beyond the hydro ramp/energy bounds: uncontrolled UFLS (assumed model).
        deficit = info["hydro_mw"] - state.hydro.max_mw
        ufls = deficit * float(lim["ufls_overshoot"])
    net, applied = prepare(state, event, actions)
    if ufls > 0:
        ufls_left = ufls
        for bus in reversed(LOAD_BUSES):                         # UFLS blocks act at the load end first
            ufls_left -= _apply_shed(net, bus, ufls_left)
            if ufls_left <= 1e-6:
                break
        ufls -= max(ufls_left, 0.0)
    net["total_load_mw"] = float(net.load.p_mw[net.load.in_service].sum())
    trips = list(event.lines) + list(actions.open_lines)
    res = simulate_cascade(net, trips, loading_threshold=float(lim["loading_trip_pct"])) if trips else None
    cascade_loss = float(res.load_lost_mw) if res is not None else 0.0
    if res is None:                                              # tie loss only: check the steady state
        cascade = info.get("max_loading_pct", 0.0) >= lim["loading_trip_pct"]
        converged = info["converged"]
    else:
        cascade = res.total_lines_tripped > len(trips)
        converged = bool(res.converged)
    if not converged:
        # AC solve failed after the event: voltage collapse. Everything not already shed is lost
        # (P1's engine stops at that point and reports only the load shed so far).
        cascade = True
        cascade_loss = float(net["total_load_mw"])
    explicit = applied["shed_mw"]
    total_lost = explicit + ufls + cascade_loss
    voltage_ok = info["converged"] and lim["vm_min_pu"] <= info.get("vm_min", 0) and info.get("vm_max", 9) <= lim["vm_max_pu"]
    # Verified = the only load lost is the intended controlled shed: no further trips, no UFLS,
    # no load cut off by islanding, voltages inside the band and every line below the trip level.
    trip_sequence = [{"iteration": int(s["iteration"]), "line": int(s["line_idx"]), "name": str(s["name"]),
                      "reason": str(s["reason"]),
                      "loading_pct": None if s["loading_pct"] is None else float(s["loading_pct"])}
                     for s in (res.line_trip_sequence if res is not None else [])]
    critical = []
    if info["converged"]:
        live = post.line.index[post.line.in_service & post.res_line.loading_percent.notna()]
        ranked = post.res_line.loading_percent.reindex(live).sort_values(ascending=False).head(5)
        critical = [{"line": int(i), "name": str(post.line.at[i, "name"]), "loading_pct": float(v)}
                    for i, v in ranked.items()]
    hydro_ok = info["converged"] and state.hydro.min_mw - 0.5 <= info.get("hydro_mw", 0.0)
    verified = bool(converged and not cascade and ufls <= 1e-6 and cascade_loss < 0.5 and voltage_ok
                    and hydro_ok and info.get("max_loading_pct", 999) < lim["loading_trip_pct"])
    return {
        "verified": verified, "cascade": bool(cascade), "converged": converged, "voltage_ok": bool(voltage_ok), "hydro_ok": bool(hydro_ok),
        "explicit_shed_mw": explicit, "ufls_mw": ufls, "cascade_loss_mw": cascade_loss,
        "total_lost_mw": total_lost, "load_lost_pct": 100.0 * total_lost / max(state.total_load_mw, 1e-6),
        "max_loading_pct": info.get("max_loading_pct"), "vm_min": info.get("vm_min"), "vm_max": info.get("vm_max"),
        "hydro_mw": info.get("hydro_mw"), "hydro_delta_mw": (info.get("hydro_mw") or 0.0) - state.hydro.base_mw,
        "tie_mw": applied["tie_mw"], "lines_tripped": int(res.total_lines_tripped) if res is not None else 0,
        "actions": actions.as_dict(), "n_actions": actions.count(),
        "trip_sequence": trip_sequence, "critical_lines": critical,
    }
