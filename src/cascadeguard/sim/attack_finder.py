# OWNER: P1 | STATUS: ACTIVE
"""Adversarial worst-case contingency and attack finder for transmission grids.

Implements P1-8:
  - Beam search and greedy search to discover minimum-k combinations causing maximum corridor blackout
  - Verifies candidate outages against AC cascade simulation
"""

from __future__ import annotations

import heapq
from typing import Any
import pandapower as pp

from cascadeguard.sim.cascade_engine import simulate_cascade
from cascadeguard.sim.outcomes import CascadeResult


def find_worst_case_attack(
    net: pp.pandapowerNet,
    k_max: int = 2,
    beam_width: int = 5,
) -> dict[str, Any]:
    """Find the worst-case line outage combinations of size up to k_max using beam search."""
    num_lines = len(net.line)
    
    # Initial beam with single outages
    beam: list[tuple[float, list[int], CascadeResult]] = []

    for line_idx in range(num_lines):
        res = simulate_cascade(net, initial_trips=[line_idx])
        score = res.load_lost_mw * 2.0 + res.total_lines_tripped * 5.0
        beam.append((score, [line_idx], res))

    beam.sort(key=lambda x: x[0], reverse=True)
    beam = beam[:beam_width]

    # Expand beam up to k_max
    current_k = 1
    best_overall = beam[0]

    while current_k < k_max:
        current_k += 1
        candidates: list[tuple[float, list[int], CascadeResult]] = []

        for score, current_trips, _ in beam:
            last_trip = current_trips[-1]
            for next_line in range(last_trip + 1, num_lines):
                new_trips = current_trips + [next_line]
                res = simulate_cascade(net, initial_trips=new_trips)
                new_score = res.load_lost_mw * 2.0 + res.total_lines_tripped * 5.0
                candidates.append((new_score, new_trips, res))

        if not candidates:
            break

        candidates.sort(key=lambda x: x[0], reverse=True)
        beam = candidates[:beam_width]
        if beam[0][0] > best_overall[0]:
            best_overall = beam[0]

    worst_score, worst_trips, worst_res = best_overall
    return {
        "k": len(worst_trips),
        "worst_trips": worst_trips,
        "worst_trip_names": worst_res.initial_trip_names,
        "total_lines_tripped": worst_res.total_lines_tripped,
        "load_lost_mw": worst_res.load_lost_mw,
        "bengaluru_load_lost_mw": worst_res.bengaluru_load_lost_mw,
        "blackout": worst_res.blackout,
    }
