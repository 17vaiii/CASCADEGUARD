"""Synthetic renewable output profiles and pandapower injection helper."""
from __future__ import annotations

from dataclasses import dataclass
import math

import pandapower as pp


@dataclass(frozen=True)
class RenewableScenario:
    name: str
    solar_mw: float
    wind_mw: float
    hour: int = 12
    source: str = "assumed synthetic scenario"


def renewable_profile(season: str, hour: int, *, solar_capacity_mw: float = 35.0,
                      wind_capacity_mw: float = 25.0) -> RenewableScenario:
    """Deterministic illustrative solar/wind profile (hour 0–23)."""
    if not 0 <= hour <= 23:
        raise ValueError("hour must be in 0..23")
    seasonal = {"monsoon": (0.65, 0.8), "post_monsoon": (0.8, 0.65), "summer": (0.9, 0.45)}
    if season not in seasonal:
        raise ValueError(f"Unknown season: {season}")
    solar_factor, wind_factor = seasonal[season]
    daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12))
    wind_wave = 0.65 + 0.25 * math.sin(2 * math.pi * hour / 24 + 0.6)
    return RenewableScenario(f"{season}_{hour:02d}", solar_capacity_mw * solar_factor * daylight,
                             wind_capacity_mw * wind_factor * wind_wave, hour)


def apply_renewable_scenario(net, scenario: RenewableScenario, *, bus_name: str = "NELAMANGALA") -> list[int]:
    """Add synthetic solar and wind generators at the named corridor bus."""
    candidates = [int(i) for i, name in net.bus.name.items() if bus_name in str(name).upper()]
    bus = candidates[0] if candidates else int(net.load.iloc[-1].bus)
    indices = []
    for technology, output in (("SOLAR", scenario.solar_mw), ("WIND", scenario.wind_mw)):
        idx = pp.create_sgen(net, bus=bus, p_mw=max(0.0, output), q_mvar=0.0,
                             name=f"SYNTHETIC_{technology}_{scenario.name}")
        indices.append(int(idx))
    net["renewable_scenario"] = scenario.name
    net["renewable_generation_mw"] = scenario.solar_mw + scenario.wind_mw
    net["renewable_sgen_indices"] = indices
    net["renewable_source"] = scenario.source
    return indices
