# OWNER: P1 | STATUS: ACTIVE
"""Contingency enumeration and scanning for N-1, N-2, and N-k line outages."""

from __future__ import annotations

import itertools
from typing import Iterator
import pandapower as pp

from cascadeguard.sim.cascade_engine import simulate_cascade
from cascadeguard.sim.outcomes import CascadeResult


def enumerate_contingencies(num_lines: int, k: int = 1) -> Iterator[list[int]]:
    """Yield all combinations of k line outages from num_lines."""
    for combo in itertools.combinations(range(num_lines), k):
        yield list(combo)


def scan_contingencies(
    net: pp.pandapowerNet,
    k: int = 1,
    limit: int | None = None,
    loading_threshold: float = 100.0,
) -> list[CascadeResult]:
    """Execute cascade simulations for all N-k line contingencies."""
    num_lines = len(net.line)
    results = []
    count = 0

    for trips in enumerate_contingencies(num_lines, k=k):
        if limit is not None and count >= limit:
            break
        res = simulate_cascade(net, initial_trips=trips, loading_threshold=loading_threshold)
        results.append(res)
        count += 1

    # Sort descending by load loss
    results.sort(key=lambda r: (r.load_lost_mw, r.total_lines_tripped), reverse=True)
    return results
