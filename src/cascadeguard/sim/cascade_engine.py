# OWNER: P1 | STATUS: ACTIVE
"""Iterative AC power flow cascading failure simulation engine.

Implements P1-2:
  1. Trip initial lines
  2. Detect network islands and shed unpowered loads
  3. Solve AC power flow
  4. Identify lines exceeding overcurrent thresholds
  5. Trip overloaded lines
  6. Repeat iteratively until stable or corridor collapses
"""

from __future__ import annotations

import copy
from typing import Any
import pandapower as pp

from cascadeguard.sim.islanding import detect_islands, island_has_generation, shed_island_loads
from cascadeguard.sim.outcomes import CascadeResult, CascadeStep
from cascadeguard.sim.trip_rules import identify_overloaded_lines


def simulate_cascade(
    net: pp.pandapowerNet,
    initial_trips: list[int],
    loading_threshold: float = 100.0,
    max_iterations: int = 20,
) -> CascadeResult:
    """Run iterative AC cascade failure simulation on a grid network."""
    net = copy.deepcopy(net)
    total_load = float(net.get("total_load_mw", net.load.p_mw.sum()))
    season_name = str(net.get("season_name", "post_monsoon"))

    steps: list[CascadeStep] = []
    all_tripped: set[int] = set()
    all_affected_buses: set[int] = set()
    trip_sequence: list[dict[str, Any]] = []

    def get_line_name(idx: int) -> str:
        try:
            return str(net.line.at[idx, "name"])
        except Exception:
            return f"line_{idx}"

    # Step 0: Apply initial contingency outages
    initial_names = []
    for li in initial_trips:
        li = int(li)
        if li in net.line.index and net.line.at[li, "in_service"]:
            net.line.at[li, "in_service"] = False
            all_tripped.add(li)
            nm = get_line_name(li)
            initial_names.append(nm)
            trip_sequence.append({
                "line_idx": li,
                "name": nm,
                "iteration": 0,
                "reason": "initial",
                "loading_pct": None,
            })

    cumulative_shed = 0.0

    # Handle islands after initial outage
    islands = detect_islands(net)
    for isl in islands:
        if not island_has_generation(net, isl):
            shed, aff = shed_island_loads(net, isl)
            cumulative_shed += shed
            all_affected_buses.update(aff)

    step0 = CascadeStep(
        iteration=0,
        tripped_lines=list(all_tripped),
        tripped_names=list(initial_names),
        reason="initial",
        load_served_mw=max(0.0, total_load - cumulative_shed),
        load_lost_mw=cumulative_shed,
        islands=len(islands),
    )
    steps.append(step0)

    # Iterative cascade propagation loop
    converged = True
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        # Check if any load or generation remains connected
        active_lines = net.line.in_service.sum()
        if active_lines == 0 or net.ext_grid.in_service.sum() == 0:
            break

        # Solve AC power flow
        try:
            pp.runpp(net, algorithm="nr", init="dc", max_iteration=50, tolerance_mva=1e-5, numba=False)
            converged = bool(net.converged)
        except Exception:
            converged = False

        if not converged:
            break

        # Check for overloaded lines
        overloaded = identify_overloaded_lines(net, loading_threshold=loading_threshold)
        if not overloaded:
            # Grid stabilized!
            break

        # Trip overloaded lines
        new_tripped = []
        new_names = []
        for line_idx, load_pct in overloaded.items():
            net.line.at[line_idx, "in_service"] = False
            all_tripped.add(line_idx)
            new_tripped.append(line_idx)
            nm = get_line_name(line_idx)
            new_names.append(nm)
            trip_sequence.append({
                "line_idx": line_idx,
                "name": nm,
                "iteration": iteration,
                "reason": "overload",
                "loading_pct": load_pct,
            })

        # Check and shed new disconnected islands
        islands = detect_islands(net)
        for isl in islands:
            if not island_has_generation(net, isl):
                shed, aff = shed_island_loads(net, isl)
                cumulative_shed += shed
                all_affected_buses.update(aff)

        step = CascadeStep(
            iteration=iteration,
            tripped_lines=new_tripped,
            tripped_names=new_names,
            reason="overload",
            overloaded_pct=overloaded,
            load_served_mw=max(0.0, total_load - cumulative_shed),
            load_lost_mw=cumulative_shed,
            islands=len(islands),
            converged=converged,
        )
        steps.append(step)

    # Compute endpoint (Peenya / Bengaluru) metrics
    peenya_idx = None
    if "name_to_idx" in net and "PEENYA" in net["name_to_idx"]:
        peenya_idx = net["name_to_idx"]["PEENYA"]

    bengaluru_load = 0.0
    bengaluru_lost = 0.0
    if peenya_idx is not None and "bus_loads_mw" in net:
        bengaluru_load = float(net["bus_loads_mw"].get(peenya_idx, 0.0))
        if peenya_idx in all_affected_buses:
            bengaluru_lost = bengaluru_load

    total_lines = len(net.line)
    total_tripped = len(all_tripped)
    lines_surviving = total_lines - total_tripped
    load_lost = min(total_load, cumulative_shed)
    load_served = max(0.0, total_load - load_lost)

    result = CascadeResult(
        initial_trips=list(initial_trips),
        initial_trip_names=initial_names,
        steps=steps,
        cascade_depth=len(steps) - 1,
        total_lines_tripped=total_tripped,
        total_lines=total_lines,
        lines_surviving=lines_surviving,
        load_served_mw=round(load_served, 2),
        load_lost_mw=round(load_lost, 2),
        bengaluru_load_mw=round(bengaluru_load, 2),
        bengaluru_load_lost_mw=round(bengaluru_lost, 2),
        bengaluru_load_shed_pct=round((bengaluru_lost / max(bengaluru_load, 1e-3)) * 100.0, 2),
        failed_lines=sorted(list(all_tripped)),
        affected_buses=sorted(list(all_affected_buses)),
        total_load_mw=round(total_load, 2),
        load_shed_pct=round((load_lost / max(total_load, 1e-3)) * 100.0, 2),
        islands=len(islands),
        blackout=(load_served == 0.0),
        converged=converged,
        season=season_name,
        line_trip_sequence=trip_sequence,
    )
    return result
