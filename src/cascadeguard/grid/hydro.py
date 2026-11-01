# OWNER: P1 | STATUS: ACTIVE
"""Seasonal hydro dispatch constraints for Sharavathi corridor.

Implements P1-5: Linganamakki reservoir parameters, ramp rates, daily energy budgets,
and feasible generation dispatch under hydrological limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml


@dataclass
class ReservoirConfig:
    name: str = "Linganamakki"
    full_capacity_mcm: float = 4482.0
    min_operating_mcm: float = 1500.0
    turbine_capacity_mw: float = 1035.0
    efficiency: float = 0.88
    head_m: float = 335.0
    source: str = "assumed"


@dataclass
class HydroDispatchState:
    energy_used_mwh: float = 0.0
    previous_mw: float | None = None
    reservoir_mcm: float | None = None


@dataclass(frozen=True)
class HydroDispatch:
    target_mw: float
    dispatched_mw: float
    limited_by: str | None
    energy_used_mwh: float
    reservoir_mcm: float | None = None


def dispatch_hydro(
    target_mw: float,
    season_max_mw: float,
    season_min_mw: float,
    ramp_limit_mw: float,
    daily_energy_limit_mwh: float,
    state: HydroDispatchState,
    duration_hours: float = 1.0,
) -> tuple[HydroDispatch, HydroDispatchState]:
    """Calculate feasible dispatch bounded by turbine, ramp, and reservoir daily energy."""
    p_req = max(0.0, float(target_mw))
    limited_by: str | None = None

    # Ramp rate constraints
    if state.previous_mw is not None:
        p_max_ramp = state.previous_mw + ramp_limit_mw
        p_min_ramp = max(0.0, state.previous_mw - ramp_limit_mw)
        if p_req > p_max_ramp:
            p_req = p_max_ramp
            limited_by = "ramp_up"
        elif p_req < p_min_ramp:
            p_req = p_min_ramp
            limited_by = "ramp_down"

    # Season capacity limits
    if p_req > season_max_mw:
        p_req = season_max_mw
        limited_by = "capacity_max"
    elif p_req < season_min_mw:
        p_req = season_min_mw
        limited_by = "capacity_min"

    # Daily energy budget
    energy_headroom = max(0.0, daily_energy_limit_mwh - state.energy_used_mwh)
    p_max_energy = energy_headroom / max(duration_hours, 1e-3)
    if p_req > p_max_energy:
        p_req = p_max_energy
        limited_by = "daily_energy_limit"

    new_used = state.energy_used_mwh + p_req * duration_hours
    new_state = HydroDispatchState(
        energy_used_mwh=new_used,
        previous_mw=p_req,
        reservoir_mcm=state.reservoir_mcm,
    )

    result = HydroDispatch(
        target_mw=round(float(target_mw), 2),
        dispatched_mw=round(float(p_req), 2),
        limited_by=limited_by,
        energy_used_mwh=round(new_used, 2),
        reservoir_mcm=state.reservoir_mcm,
    )
    return result, new_state
