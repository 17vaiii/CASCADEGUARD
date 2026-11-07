# OWNER: P5 | NEEDS: P1 | STATUS: ACTIVE
"""H2 / H3: hydro redispatch bounds for remedial actions, via P1's ``dispatch_hydro``.

Within the remedial-action window the Sharavathi (Linganamakki) units may change output only by
``ramp_rate x window``. Sustained output for the rest of the day is capped by the daily energy
budget (H3: reservoir-constrained dispatch). Below a reservoir floor no ramp-up is allowed.
P1's ``grid.hydro.dispatch_hydro`` computes the feasible values, so P5 and P1 share one rule set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cascadeguard.grid.hydro import HydroDispatchState, dispatch_hydro
from cascadeguard.grid.seasons import SeasonProfile


@dataclass(frozen=True)
class HydroBounds:
    base_mw: float
    min_mw: float
    max_mw: float
    ramp_limit_mw: float
    energy_cap_mw: float          # sustainable output for the remaining hours of the day
    limited_by_up: str | None
    limited_by_down: str | None
    ramp_up_allowed: bool

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def base_hydro_dispatch(season: SeasonProfile, demand_mw: float, budget_use_fraction: float = 1.0) -> float:
    """Pre-contingency schedule: hydro covers demand up to capacity and a share of the daily budget
    (the rest of the budget is the reservoir's emergency reserve)."""
    avg_budget = budget_use_fraction * season.daily_energy_limit_mwh / 24.0
    return max(season.min_generation_mw, min(demand_mw, season.max_generation_mw, avg_budget))


def hydro_bounds(season: SeasonProfile, base_mw: float, cfg: dict[str, Any]) -> HydroBounds:
    """Feasible hydro output range within the remedial-action window (MW).

    Upward bound: ramp within the response window, season capacity, and the daily energy budget
    assuming the raised output is held for ``emergency_duration_h`` and the schedule (``base_mw``)
    is kept for the rest of the day (H3).
    """
    d = cfg["dispatch"]
    hour = float(d["hour_of_day"])
    window_h = float(d["response_window_min"]) / 60.0
    ramp = season.ramp_rate_mw_per_min * float(d["response_window_min"])
    used = base_mw * hour
    remaining_h = max(24.0 - hour, 1.0)
    emergency_h = min(float(d.get("emergency_duration_h", remaining_h)), remaining_h)
    committed = used + base_mw * (remaining_h - emergency_h)     # energy already spoken for today
    state = HydroDispatchState(energy_used_mwh=committed, previous_mw=base_mw)
    up, _ = dispatch_hydro(season.max_generation_mw, season.max_generation_mw, season.min_generation_mw,
                           ramp, season.daily_energy_limit_mwh, state, duration_hours=emergency_h)
    state = HydroDispatchState(energy_used_mwh=used, previous_mw=base_mw)
    down, _ = dispatch_hydro(0.0, season.max_generation_mw, season.min_generation_mw, ramp,
                             season.daily_energy_limit_mwh, state, duration_hours=window_h)
    up_allowed = season.reservoir_level_pct > float(d["reservoir_floor_pct"])
    max_mw = up.dispatched_mw - float(d.get("hydro_reserve_mw", 0.0)) if up_allowed else base_mw
    energy_cap = max(0.0, season.daily_energy_limit_mwh - used) / remaining_h
    return HydroBounds(base_mw=base_mw, min_mw=min(down.dispatched_mw, base_mw), max_mw=max(max_mw, base_mw)
                       if up_allowed else base_mw, ramp_limit_mw=ramp, energy_cap_mw=energy_cap,
                       limited_by_up=up.limited_by if up_allowed else "reservoir_floor",
                       limited_by_down=down.limited_by, ramp_up_allowed=up_allowed)
