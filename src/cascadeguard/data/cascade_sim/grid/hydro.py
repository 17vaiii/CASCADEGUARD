"""
grid/hydro.py — Seasonal hydro dispatch constraints for Sharavathi corridor.

Loads hydro.yaml and provides seasonal profiles that constrain:
  - Maximum/minimum generation at Sharavathi
  - Ramp rate limits
  - Daily energy budget
  - Corridor load scaling (seasonal demand variation)

Public API
----------
load_hydro_config(path) → HydroConfig
get_season(name) → SeasonProfile
get_all_seasons() → dict[str, SeasonProfile]
apply_season(net, season) → net  (mutates load scale + gen limits)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"


@dataclass
class ReservoirConfig:
    """Linganamakki reservoir parameters."""
    name: str
    full_capacity_mcm: float
    min_operating_mcm: float
    turbine_capacity_mw: float
    efficiency: float
    head_m: float
    source: str = "assumed"


@dataclass
class SeasonProfile:
    """Seasonal operating conditions for the corridor."""
    name: str
    months: list[int]
    description: str
    reservoir_level_pct: float
    max_generation_mw: float
    min_generation_mw: float
    ramp_rate_mw_per_min: float
    daily_energy_limit_mwh: float
    inflow_cumecs: float
    corridor_load_scale: float
    source: str = "assumed"

    @property
    def available_hours(self) -> float:
        """Daily hours at max generation before hitting energy limit."""
        if self.max_generation_mw <= 0:
            return 0.0
        return self.daily_energy_limit_mwh / self.max_generation_mw

    @property
    def severity(self) -> str:
        """Qualitative stress level for this season."""
        if self.corridor_load_scale >= 1.1:
            return "critical"
        if self.corridor_load_scale >= 0.95:
            return "moderate"
        return "comfortable"


@dataclass
class HydroConfig:
    """Complete hydro configuration."""
    reservoir: ReservoirConfig
    seasons: dict[str, SeasonProfile]


@dataclass
class HydroDispatchState:
    """Energy and output state for a single hydro dispatch day."""
    energy_used_mwh: float = 0.0
    previous_mw: float | None = None
    reservoir_mcm: float | None = None


@dataclass(frozen=True)
class HydroDispatch:
    """Feasible hydro output for one dispatch interval."""
    requested_mw: float
    dispatched_mw: float
    curtailed_mw: float
    energy_used_mwh: float
    energy_remaining_mwh: float
    reservoir_mcm: float
    ramp_limited: bool
    energy_limited: bool


@dataclass(frozen=True)
class HydroDayResult:
    """Chronological dispatch result for one simulated operating day."""
    intervals: list[HydroDispatch]
    state: HydroDispatchState
    total_generation_mwh: float
    curtailed_energy_mwh: float


def simulate_hydro_day(
    requested_dispatch_mw: list[float], season: SeasonProfile, *,
    reservoir: ReservoirConfig | None = None, interval_minutes: float = 60.0,
    initial_state: HydroDispatchState | None = None,
) -> HydroDayResult:
    """Apply hydro water, ramp, turbine and daily-energy limits sequentially.

    Requests represent desired MW at each interval. Pass a prior state only
    when intentionally continuing a day; a new day should start with a fresh
    state so its daily energy counter resets.
    """
    if not requested_dispatch_mw:
        raise ValueError("requested_dispatch_mw must contain at least one interval")
    config = reservoir or load_hydro_config().reservoir
    state = initial_state or HydroDispatchState()
    rows = [dispatch_hydro(value, season, state, reservoir=config,
                           interval_minutes=interval_minutes)
            for value in requested_dispatch_mw]
    return HydroDayResult(
        intervals=rows, state=state,
        total_generation_mwh=sum(x.energy_used_mwh for x in rows),
        curtailed_energy_mwh=sum(x.curtailed_mw * interval_minutes / 60 for x in rows),
    )


def dispatch_hydro(
    requested_mw: float,
    season: SeasonProfile,
    state: HydroDispatchState,
    *,
    reservoir: ReservoirConfig,
    interval_minutes: float = 60.0,
) -> HydroDispatch:
    """Apply turbine, ramp-rate and daily-energy limits to a dispatch request.

    ``state`` is intentionally explicit so callers can reset each simulated
    day and carry dispatch from one interval to the next. Energy is measured
    against the configured daily budget; inflow and reservoir assumptions are
    already represented by each season's budget.
    """
    if requested_mw < 0 or interval_minutes <= 0:
        raise ValueError("requested_mw must be non-negative and interval_minutes positive")
    energy_remaining = max(0.0, season.daily_energy_limit_mwh - state.energy_used_mwh)
    interval_hours = interval_minutes / 60.0
    if state.reservoir_mcm is None:
        state.reservoir_mcm = reservoir.full_capacity_mcm * season.reservoir_level_pct / 100.0
    inflow_mcm = season.inflow_cumecs * interval_minutes * 60.0 / 1_000_000.0
    available_water_mcm = max(
        0.0, state.reservoir_mcm + inflow_mcm - reservoir.min_operating_mcm
    )
    mwh_per_m3 = 1000.0 * 9.80665 * reservoir.head_m * reservoir.efficiency / 3.6e9
    water_energy_mwh = available_water_mcm * 1_000_000.0 * mwh_per_m3
    energy_cap_mw = min(energy_remaining, water_energy_mwh) / interval_hours
    upper = min(season.max_generation_mw, reservoir.turbine_capacity_mw, energy_cap_mw)
    lower = min(season.min_generation_mw, upper)
    ramp_limited = False
    if state.previous_mw is not None:
        ramp = season.ramp_rate_mw_per_min * interval_minutes
        ramp_upper = state.previous_mw + ramp
        ramp_lower = max(0.0, state.previous_mw - ramp)
        if upper > ramp_upper:
            ramp_limited = True
        upper = min(upper, ramp_upper)
        lower = min(upper, max(lower, ramp_lower))
    dispatched = min(upper, max(lower, requested_mw))
    used = dispatched * interval_hours
    state.energy_used_mwh += used
    state.previous_mw = dispatched
    water_used_mcm = (used / mwh_per_m3) / 1_000_000.0 if mwh_per_m3 > 0 else 0.0
    state.reservoir_mcm = min(
        reservoir.full_capacity_mcm,
        max(reservoir.min_operating_mcm,
            state.reservoir_mcm + inflow_mcm - water_used_mcm),
    )
    return HydroDispatch(
        requested_mw=float(requested_mw), dispatched_mw=float(dispatched),
        curtailed_mw=float(max(0.0, requested_mw - dispatched)),
        energy_used_mwh=float(used),
        energy_remaining_mwh=float(max(0.0, energy_remaining - used)),
        reservoir_mcm=float(state.reservoir_mcm),
        ramp_limited=ramp_limited,
        energy_limited=energy_cap_mw < season.max_generation_mw,
    )


def load_hydro_config(path: Optional[Path] = None) -> HydroConfig:
    """Load and validate hydro.yaml."""
    p = path or (_CONFIG_DIR / "hydro.yaml")
    with open(p) as fh:
        raw = yaml.safe_load(fh)

    reservoir = ReservoirConfig(**raw["reservoir"])
    seasons = {}
    for name, data in raw["seasons"].items():
        seasons[name] = SeasonProfile(name=name, **data)

    return HydroConfig(reservoir=reservoir, seasons=seasons)


def get_all_seasons(path: Optional[Path] = None) -> dict[str, SeasonProfile]:
    """Return all seasonal profiles keyed by name."""
    return load_hydro_config(path).seasons


def get_season(name: str, path: Optional[Path] = None) -> SeasonProfile:
    """Return a specific seasonal profile by name."""
    seasons = get_all_seasons(path)
    if name not in seasons:
        raise ValueError(
            f"Unknown season '{name}'. Available: {list(seasons.keys())}"
        )
    return seasons[name]


def apply_season(net, season: SeasonProfile):
    """
    Apply seasonal constraints to a pandapower cascade network.
    Scales loads and stores seasonal metadata.  Mutates net in place.

    Hydro is a bounded generation injection at Sharavathi. A balancing grid
    import slack at SHIMOGA represents the wider grid and lets seasonal hydro
    limits change corridor flows.
    """
    import pandapower as pp
    # Scale loads
    base_loads = net.get("base_loads", {})
    if not base_loads:
        base_loads = {int(idx): (float(row.p_mw), float(row.q_mvar))
                      for idx, row in net.load.iterrows()}
        net["base_loads"] = base_loads
    base_load = sum(p for p, _ in base_loads.values())
    if base_load > 0:
        for idx in net.load.index:
            p, q = base_loads[int(idx)]
            net.load.at[idx, "p_mw"] = p * season.corridor_load_scale
            net.load.at[idx, "q_mvar"] = q * season.corridor_load_scale
        net["total_load_mw"] = base_load * season.corridor_load_scale

    # Store generation constraints as metadata
    net["season"] = season.name
    net["max_gen_mw"] = season.max_generation_mw
    net["min_gen_mw"] = season.min_generation_mw
    net["ramp_rate_mw_per_min"] = season.ramp_rate_mw_per_min
    net["daily_energy_mwh"] = season.daily_energy_limit_mwh
    net["reservoir_pct"] = season.reservoir_level_pct
    net["hydro_source"] = season.source
    net["hydro_inflow_cumecs"] = season.inflow_cumecs

    hydro_config = load_hydro_config()
    state = net.get("hydro_dispatch_state") or HydroDispatchState()
    requested_mw = min(float(net.get("total_load_mw", 0.0)), season.max_generation_mw)
    dispatch = dispatch_hydro(
        requested_mw, season, state, reservoir=hydro_config.reservoir,
    )
    net.sgen.at[net["hydro_sgen_idx"], "p_mw"] = dispatch.dispatched_mw
    net["hydro_dispatch_state"] = state
    net["hydro_dispatch_mw"] = dispatch.dispatched_mw
    net["hydro_dispatch_curtailed_mw"] = dispatch.curtailed_mw
    net["hydro_energy_remaining_mwh"] = dispatch.energy_remaining_mwh
    net["reservoir_level_mcm"] = dispatch.reservoir_mcm
    net["hydro_ramp_limited"] = dispatch.ramp_limited
    net["hydro_energy_limited"] = dispatch.energy_limited

    net.ext_grid.at[int(net["origin_slack_idx"]), "in_service"] = False
    import_idx = net.get("import_slack_idx")
    if import_idx is None:
        named_buses = {int(idx): str(name).upper()
                       for idx, name in net.bus["name"].items()}
        import_buses = [idx for idx, name in named_buses.items()
                        if "SHIMOGA" in name]
        import_bus = import_buses[0] if import_buses else int(net.load.iloc[0].bus)
        import_idx = pp.create_ext_grid(
            net, bus=import_bus, vm_pu=1.0, name="GRID_IMPORT",
        )
        net["import_slack_idx"] = import_idx

    return net


def season_summary(season: SeasonProfile, reservoir: ReservoirConfig) -> dict:
    """Build a summary dict for API responses."""
    return {
        "name": season.name,
        "months": season.months,
        "description": season.description,
        "severity": season.severity,
        "reservoir_level_pct": season.reservoir_level_pct,
        "max_generation_mw": season.max_generation_mw,
        "min_generation_mw": season.min_generation_mw,
        "ramp_rate_mw_per_min": season.ramp_rate_mw_per_min,
        "daily_energy_limit_mwh": season.daily_energy_limit_mwh,
        "available_hours_at_max": round(season.available_hours, 1),
        "inflow_cumecs": season.inflow_cumecs,
        "corridor_load_scale": season.corridor_load_scale,
        "turbine_capacity_mw": reservoir.turbine_capacity_mw,
        "source": season.source,
    }

