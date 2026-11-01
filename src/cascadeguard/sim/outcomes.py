# OWNER: P1 | STATUS: ACTIVE
"""Typed outcome records and step traces for cascade simulations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CascadeStep:
    """One iterative step of the cascade simulation."""
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
    """Complete summary and trace of an AC cascading failure simulation."""
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
    loss_mw: float = 0.0
    islands: int = 1
    blackout: bool = False
    converged: bool = True
    season: str = "post_monsoon"
    line_trip_sequence: list[dict[str, Any]] = field(default_factory=list)
