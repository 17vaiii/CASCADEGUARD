"""
grid/cascade.py — Cascading failure simulation engine.

Simulates iterative line tripping on the Sharavathi corridor.  The cascade
network uses **unfolded dual circuits** (2 parallel lines per section) so that
an N-1 contingency on a single circuit realistically overloads the surviving
parallel path, potentially triggering a propagating cascade.

Public API
----------
build_cascade_net(topology, load_scale, season)
    → pp.pandapowerNet with dual circuits and cascade metadata

simulate_cascade(net, initial_trips, loading_threshold, max_iterations)
    → CascadeResult with step-by-step trace

contingency_scan(net, k, loading_threshold, top_n)
    → sorted list of CascadeResult for all N-k contingencies
"""

from __future__ import annotations

import copy
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandapower as pp

from grid.config import TopologyConfig, load_topology

log = logging.getLogger("cascade")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CascadeStep:
    """One iteration of the cascade process."""
    iteration: int
    tripped_lines: list[int] = field(default_factory=list)
    tripped_names: list[str] = field(default_factory=list)
    reason: str = "initial"  # "initial" | "overload" | "island_collapse"
    overloaded_pct: dict[int, float] = field(default_factory=dict)
    load_served_mw: float = 0.0
    load_lost_mw: float = 0.0
    islands: int = 1
    converged: bool = True


@dataclass
class CascadeResult:
    """Full result of a cascade simulation."""
    initial_trips: list[int] = field(default_factory=list)
    initial_trip_names: list[str] = field(default_factory=list)
    steps: list[CascadeStep] = field(default_factory=list)
    cascade_depth: int = 0
    total_lines_tripped: int = 0
    total_lines: int = 0
    lines_surviving: int = 0
    load_served_mw: float = 0.0
    load_lost_mw: float = 0.0
    bengaluru_load_mw: float = 0.0
    bengaluru_load_lost_mw: float = 0.0
    bengaluru_load_shed_pct: float = 0.0
    failed_lines: list[int] = field(default_factory=list)
    affected_buses: list[int] = field(default_factory=list)
    total_load_mw: float = 0.0
    load_shed_pct: float = 0.0
    gen_mw: float = 0.0
    hydro_generation_mw: float = 0.0
    loss_mw: float = 0.0
    islands: int = 1
    blackout: bool = False
    final_vm_pu: dict[int, float] = field(default_factory=dict)
    final_line_loading: dict[int, float] = field(default_factory=dict)
    converged: bool = True
    season: str = "post_monsoon"
    line_trip_sequence: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Network builder (dual-circuit unfolded)
# ---------------------------------------------------------------------------

def build_cascade_net(
    topology: TopologyConfig | None = None,
    load_scale: float = 1.0,
) -> pp.pandapowerNet:
    """
    Build a pandapower network with **unfolded dual circuits** for cascade
    analysis.  Each section of the corridor gets two parallel lines (A and B)
    with single-circuit impedance, so tripping one circuit realistically
    doubles loading on the other.

    Extra attributes on net:
        net["cascade_pairs"]  = {section_idx: (line_idx_A, line_idx_B)}
        net["line_section"]   = {line_idx: section_idx}
        net["line_circuit"]   = {line_idx: "A" | "B"}
        net["section_km"]     = {section_idx: (from_km, to_km)}
        net["section_names"]  = {section_idx: (from_name, to_name)}
        net["bus_km"]         = {bus_idx: km}
        net["bus_loads_mw"]   = {bus_idx: p_mw}
        net["total_load_mw"]  = total load
    """
    topo = topology or load_topology()
    net = pp.create_empty_network(name="SharavathiCascade", f_hz=50.0)

    # --- Build ordered bus positions (substations + taps) ---
    positions: list[tuple[float, str, bool]] = []  # (km, name, is_substation)
    sub_kms = {b.km for b in topo.buses}
    for b in topo.buses:
        positions.append((b.km, b.id, True))

    corridor_len = max(b.km for b in topo.buses)
    step = topo.tap_spacing_km
    km = step
    while km < corridor_len:
        if km not in sub_kms:
            positions.append((km, f"TAP_{int(km)}", False))
        km += step
    positions.sort(key=lambda x: x[0])

    # --- Create buses ---
    bus_km: dict[int, float] = {}
    name_to_idx: dict[str, int] = {}
    for km_val, name, is_sub in positions:
        idx = pp.create_bus(net, vn_kv=topo.base_kv, name=name)
        bus_km[idx] = km_val
        name_to_idx[name] = idx

    # --- External grid (slack) at Sharavathi ---
    slack_bus = name_to_idx[topo.gen.bus]
    source_idx = pp.create_ext_grid(net, bus=slack_bus, vm_pu=topo.gen.vm_pu,
                                    name=f"GEN_{topo.gen.bus}")
    hydro_idx = pp.create_sgen(net, bus=slack_bus, p_mw=0.0, q_mvar=0.0,
                               name="LINGANAMAKKI_HYDRO", in_service=True)

    # --- Lines: dual circuits per section ---
    # Single-circuit parameters (unfold the 2-circuit equivalent)
    r_per_km = topo.lines.r_ohm_per_km * topo.lines.circuits * 2
    x_per_km = topo.lines.x_ohm_per_km * topo.lines.circuits * 2
    c_per_km = topo.lines.c_nf_per_km / (topo.lines.circuits * 2)
    max_i = topo.lines.max_i_ka / (topo.lines.circuits * 2)

    cascade_pairs: dict[int, tuple[int, int]] = {}
    line_section: dict[int, int] = {}
    line_circuit: dict[int, str] = {}
    section_km: dict[int, tuple[float, float]] = {}
    section_names: dict[int, tuple[str, str]] = {}

    for sec_idx in range(len(positions) - 1):
        km_from, name_from, _ = positions[sec_idx]
        km_to, name_to, _ = positions[sec_idx + 1]
        length = km_to - km_from
        bus_from = name_to_idx[name_from]
        bus_to = name_to_idx[name_to]

        line_a = pp.create_line_from_parameters(
            net, from_bus=bus_from, to_bus=bus_to,
            length_km=length,
            r_ohm_per_km=r_per_km, x_ohm_per_km=x_per_km,
            c_nf_per_km=c_per_km, max_i_ka=max_i,
            name=f"S{sec_idx}_A_{name_from}-{name_to}",
        )
        line_b = pp.create_line_from_parameters(
            net, from_bus=bus_from, to_bus=bus_to,
            length_km=length,
            r_ohm_per_km=r_per_km, x_ohm_per_km=x_per_km,
            c_nf_per_km=c_per_km, max_i_ka=max_i,
            name=f"S{sec_idx}_B_{name_from}-{name_to}",
        )

        cascade_pairs[sec_idx] = (line_a, line_b)
        line_section[line_a] = sec_idx
        line_section[line_b] = sec_idx
        line_circuit[line_a] = "A"
        line_circuit[line_b] = "B"
        section_km[sec_idx] = (km_from, km_to)
        section_names[sec_idx] = (name_from, name_to)

    # --- Loads ---
    bus_loads_mw: dict[int, float] = {}
    total_load = 0.0
    for lc in topo.loads:
        bus_idx = name_to_idx[lc.bus]
        p = lc.p_mw * load_scale
        q = lc.q_mvar * load_scale
        pp.create_load(net, bus=bus_idx, p_mw=p, q_mvar=q, name=f"LOAD_{lc.bus}")
        bus_loads_mw[bus_idx] = p
        total_load += p

    # --- Shunt capacitors ---
    for sc in topo.shunts:
        bus_idx = name_to_idx[sc.bus]
        pp.create_shunt(net, bus=bus_idx, q_mvar=-sc.q_mvar_cap,
                        name=f"CAP_{sc.bus}")

    # --- Store metadata ---
    net["cascade_pairs"] = cascade_pairs
    net["line_section"] = line_section
    net["line_circuit"] = line_circuit
    net["section_km"] = section_km
    net["section_names"] = section_names
    net["bus_km"] = bus_km
    net["bus_loads_mw"] = bus_loads_mw
    net["total_load_mw"] = total_load
    net["name_to_idx"] = name_to_idx
    net["hydro_sgen_idx"] = hydro_idx
    net["origin_slack_idx"] = source_idx
    net["import_slack_idx"] = None

    return net


# ---------------------------------------------------------------------------
# Island detection
# ---------------------------------------------------------------------------

def _find_islands(net: pp.pandapowerNet) -> list[set[int]]:
    """Return sets of bus indices for each electrical island."""
    import networkx as nx
    G = nx.Graph()
    for idx in net.bus.index:
        if net.bus.at[idx, "in_service"]:
            G.add_node(idx)
    for idx in net.line.index:
        if net.line.at[idx, "in_service"]:
            G.add_edge(
                net.line.at[idx, "from_bus"],
                net.line.at[idx, "to_bus"],
            )
    return [set(c) for c in nx.connected_components(G)]


def _island_has_gen(net: pp.pandapowerNet, island: set[int]) -> bool:
    """Check whether an island contains an active pandapower slack source."""
    for idx in net.ext_grid.index:
        if net.ext_grid.at[idx, "in_service"] and \
           net.ext_grid.at[idx, "bus"] in island:
            return True
    return False


def _island_load(net: pp.pandapowerNet, island: set[int]) -> float:
    """Total MW load in an island."""
    total = 0.0
    for idx in net.load.index:
        if net.load.at[idx, "in_service"] and \
           net.load.at[idx, "bus"] in island:
            total += net.load.at[idx, "p_mw"]
    return total


def _shed_island_loads(net: pp.pandapowerNet, island: set[int]) -> float:
    """Black out an island without a slack source and return its shed load."""
    shed = 0.0
    for idx in net.load.index:
        if net.load.at[idx, "in_service"] and \
           net.load.at[idx, "bus"] in island:
            shed += net.load.at[idx, "p_mw"]
            net.load.at[idx, "in_service"] = False
    # A fixed-P hydro injection cannot balance a disconnected island or act as
    # a pandapower slack. Curtail it when its island has lost the grid tie.
    for idx in net.sgen.index:
        if net.sgen.at[idx, "in_service"] and net.sgen.at[idx, "bus"] in island:
            net.sgen.at[idx, "in_service"] = False
    return shed


# ---------------------------------------------------------------------------
# Core cascade simulation
# ---------------------------------------------------------------------------

def simulate_cascade(
    net: pp.pandapowerNet,
    initial_trips: list[int],
    loading_threshold: float = 100.0,
    max_iterations: int = 20,
    verbose: bool = False,
) -> CascadeResult:
    """
    Iterative cascade simulation.

    1. Trip the initial lines (set in_service=False)
    2. Detect and shed loads on generator-less islands
    3. Run AC power flow
    4. Find lines exceeding loading_threshold
    5. Trip those overloaded lines
    6. Repeat from step 2 until stable or blackout

    Parameters
    ----------
    net : pp.pandapowerNet
        A cascade network built by build_cascade_net().  **Mutated in place.**
    initial_trips : list[int]
        Line indices to trip initially.
    loading_threshold : float
        Lines with loading ≥ this % are tripped (default 100%).
    max_iterations : int
        Safety limit to prevent infinite loops.

    Returns
    -------
    CascadeResult
        Step-by-step trace of the cascade.
    """
    net = copy.deepcopy(net)
    total_load = net.get("total_load_mw", 0.0)
    season_name = str(net.get("season", "post_monsoon"))
    steps: list[CascadeStep] = []
    all_tripped: set[int] = set()
    trip_sequence: list[dict] = []

    # --- Resolve line names ---
    def _line_name(idx: int) -> str:
        try:
            return str(net.line.at[idx, "name"])
        except Exception:
            return f"line_{idx}"

    # --- Step 0: initial trips ---
    initial_names = []
    for li in initial_trips:
        if li not in net.line.index:
            raise ValueError(f"Unknown line index in initial_trips: {li}")
        if net.line.at[li, "in_service"]:
            net.line.at[li, "in_service"] = False
            all_tripped.add(li)
            nm = _line_name(li)
            initial_names.append(nm)
            trip_sequence.append({
                "line_idx": int(li), "name": nm,
                "iteration": 0, "reason": "initial",
                "loading_pct": None,
            })

    if verbose:
        log.info(f"Cascade: initial trips = {initial_names}")

    for iteration in range(1, max_iterations + 1):
        step = CascadeStep(iteration=iteration)

        # --- Detect islands and shed gen-less island loads ---
        islands = _find_islands(net)
        step.islands = len(islands)
        shed_total = 0.0
        for island in islands:
            if not _island_has_gen(net, island):
                shed = _shed_island_loads(net, island)
                shed_total += shed

        if shed_total > 0:
            if verbose:
                log.info(f"  Iter {iteration}: shed {shed_total:.1f} MW "
                         f"from {len(islands)} islands")

        # --- Run power flow ---
        try:
            pp.runpp(net, algorithm="nr", init="dc", max_iteration=50,
                     tolerance_mva=1e-6, numba=False)
            step.converged = True
        except pp.powerflow.LoadflowNotConverged:
            step.converged = False
            # Non-convergence often means voltage collapse / blackout
            step.reason = "pf_diverged"
            step.load_lost_mw = total_load
            step.load_served_mw = 0.0
            steps.append(step)
            break
        except Exception:
            step.converged = False
            step.reason = "pf_error"
            steps.append(step)
            break

        # --- Compute served load ---
        served = float(net.res_load.p_mw[net.load.in_service].sum()) \
            if len(net.res_load) > 0 else 0.0
        step.load_served_mw = served
        step.load_lost_mw = total_load - served

        # --- Find overloaded lines ---
        overloaded: list[int] = []
        overloaded_pct: dict[int, float] = {}
        for li in net.line.index:
            if net.line.at[li, "in_service"]:
                loading = float(net.res_line.at[li, "loading_percent"])
                if loading >= loading_threshold:
                    overloaded.append(li)
                    overloaded_pct[li] = round(loading, 1)

        step.overloaded_pct = overloaded_pct

        if not overloaded:
            # Cascade stabilized
            step.reason = "stable"
            steps.append(step)
            break

        # --- Trip overloaded lines ---
        step.reason = "overload"
        for li in overloaded:
            net.line.at[li, "in_service"] = False
            all_tripped.add(li)
            nm = _line_name(li)
            step.tripped_lines.append(li)
            step.tripped_names.append(nm)
            trip_sequence.append({
                "line_idx": int(li), "name": nm,
                "iteration": iteration, "reason": "overload",
                "loading_pct": overloaded_pct.get(li),
            })

        if verbose:
            log.info(f"  Iter {iteration}: tripped {len(overloaded)} "
                     f"overloaded lines → {step.tripped_names}")

        steps.append(step)

        # --- Check for total blackout ---
        if not any(net.line.in_service):
            break

    # --- Build final result ---
    # Final power flow for metrics
    final_vm: dict[int, float] = {}
    final_loading: dict[int, float] = {}
    try:
        pp.runpp(net, algorithm="nr", init="dc", max_iteration=50,
                 tolerance_mva=1e-6, numba=False)
        for bi in net.bus.index:
            if net.bus.at[bi, "in_service"]:
                final_vm[bi] = round(float(net.res_bus.at[bi, "vm_pu"]), 4)
        for li in net.line.index:
            if net.line.at[li, "in_service"]:
                final_loading[li] = round(
                    float(net.res_line.at[li, "loading_percent"]), 1)
        gen_mw = float(net.res_ext_grid.p_mw[net.ext_grid.in_service].sum())
        hydro_mw = 0.0
        if len(net.sgen):
            active_sgen = net.sgen.in_service
            gen_mw += float(net.res_sgen.p_mw[active_sgen].sum())
            hydro_mask = net.sgen.name.astype(str).str.contains(
                "LINGANAMAKKI|SHARAVATHI.*HYDRO", case=False, regex=True,
            ) & active_sgen
            hydro_mw = float(net.res_sgen.p_mw[hydro_mask].sum())
        loss_mw = gen_mw - float(
            net.res_load.p_mw[net.load.in_service].sum())
        served = float(net.res_load.p_mw[net.load.in_service].sum())
        converged = True
    except Exception:
        gen_mw = 0.0
        hydro_mw = 0.0
        loss_mw = 0.0
        served = 0.0
        converged = False

    lost = total_load - served
    shed_pct = (lost / total_load * 100) if total_load > 0 else 0.0
    islands = _find_islands(net)
    surviving = sum(1 for li in net.line.index if net.line.at[li, "in_service"])
    # The reduced corridor model's Bengaluru load is attached at PEENYA. Keep
    # this explicit label for attack ranking and downstream training contracts.
    bengaluru_total = 0.0
    bengaluru_served = 0.0
    bus_names = {int(idx): str(name) for idx, name in net.bus["name"].items()}
    for load_idx, load in net.load.iterrows():
        if "PEENYA" in bus_names.get(int(load.bus), "").upper() or "BENGALURU" in bus_names.get(int(load.bus), "").upper():
            amount = float(load.p_mw)
            bengaluru_total += amount
            if bool(load.in_service):
                bengaluru_served += amount
    affected_buses = sorted({int(load.bus) for _, load in net.load.iterrows()
                             if not bool(load.in_service)})
    if not converged and not affected_buses:
        affected_buses = sorted({int(bus) for bus in net.load.bus})
    if not converged:
        bengaluru_served = 0.0

    return CascadeResult(
        initial_trips=list(initial_trips),
        initial_trip_names=initial_names,
        steps=steps,
        cascade_depth=len(steps),
        total_lines_tripped=len(all_tripped),
        total_lines=len(net.line),
        lines_surviving=surviving,
        load_served_mw=round(served, 2),
        load_lost_mw=round(lost, 2),
        bengaluru_load_mw=round(bengaluru_total, 2),
        bengaluru_load_lost_mw=round(bengaluru_total - bengaluru_served, 2),
        bengaluru_load_shed_pct=(round((bengaluru_total - bengaluru_served) / bengaluru_total * 100.0, 1)
                                 if bengaluru_total > 0 else 0.0),
        failed_lines=sorted(all_tripped),
        affected_buses=affected_buses,
        total_load_mw=round(total_load, 2),
        load_shed_pct=round(shed_pct, 1),
        gen_mw=round(gen_mw, 2),
        hydro_generation_mw=round(hydro_mw, 2),
        loss_mw=round(loss_mw, 2),
        islands=len(islands),
        blackout=served < 1.0,
        final_vm_pu=final_vm,
        final_line_loading=final_loading,
        converged=converged,
        season=season_name,
        line_trip_sequence=trip_sequence,
    )


# ---------------------------------------------------------------------------
# N-k contingency scan
# ---------------------------------------------------------------------------

def contingency_scan(
    net: pp.pandapowerNet,
    k: int = 1,
    loading_threshold: float = 100.0,
    top_n: int = 20,
) -> list[dict]:
    """
    Exhaustive N-k contingency scan: try all combinations of k lines,
    simulate cascade, return top_n worst results sorted by load shed.

    For k=1, this is fast (~80 single-line trips on dual-circuit net).
    For k=2, there are ~3000 combinations — still tractable.
    For k≥3, consider using attack_finder.py beam search instead.
    """
    all_lines = [int(li) for li in net.line.index]
    results: list[dict] = []

    for combo in itertools.combinations(all_lines, k):
        trips = list(combo)
        result = simulate_cascade(
            net, trips,
            loading_threshold=loading_threshold,
        )
        results.append({
            "trips": trips,
            "trip_names": result.initial_trip_names,
            "cascade_depth": result.cascade_depth,
            "total_lines_tripped": result.total_lines_tripped,
            "load_shed_pct": result.load_shed_pct,
            "load_lost_mw": result.load_lost_mw,
            "blackout": result.blackout,
            "islands": result.islands,
        })

    results.sort(key=lambda r: r["load_shed_pct"], reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Helper: line info for API
# ---------------------------------------------------------------------------

def get_line_info(net: pp.pandapowerNet) -> list[dict]:
    """Return metadata for each line in the cascade network."""
    lines = []
    section_km = net.get("section_km", {})
    line_section = net.get("line_section", {})
    line_circuit = net.get("line_circuit", {})

    for li in net.line.index:
        sec = line_section.get(li)
        km_range = section_km.get(sec, (0, 0)) if sec is not None else (0, 0)
        lines.append({
            "line_idx": int(li),
            "name": str(net.line.at[li, "name"]),
            "section": sec,
            "circuit": line_circuit.get(li, "?"),
            "from_km": km_range[0],
            "to_km": km_range[1],
            "from_bus": int(net.line.at[li, "from_bus"]),
            "to_bus": int(net.line.at[li, "to_bus"]),
            "in_service": bool(net.line.at[li, "in_service"]),
            "length_km": float(net.line.at[li, "length_km"]),
            "max_i_ka": float(net.line.at[li, "max_i_ka"]),
        })
    return lines

