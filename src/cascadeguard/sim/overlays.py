# OWNER: P1 | STATUS: ACTIVE
"""Weather and renewable variability overlays for transmission stress testing.

Implements P1-9:
  - Generates weather-weighted trip probability multipliers (wind/storm stress)
  - Injects seasonal solar/wind renewable fluctuations into corridor operating points
"""

from __future__ import annotations

import random
from typing import Any
import pandapower as pp


def apply_weather_overlay(
    net: pp.pandapowerNet,
    storm_severity: float = 1.0,
    seed: int = 42,
) -> dict[int, float]:
    """Calculate weather-induced outage probability weights per line.
    
    Returns:
      Mapping from line index to outage failure risk multiplier.
    """
    rng = random.Random(seed)
    weights: dict[int, float] = {}

    for idx in net.line.index:
        length = float(net.line.at[idx, "length_km"])
        # Longer transmission sections face higher storm exposure
        base_risk = 0.01 * (length / 10.0)
        storm_factor = 1.0 + storm_severity * rng.uniform(0.5, 2.0)
        weights[int(idx)] = round(base_risk * storm_factor, 4)

    return weights


def apply_renewable_variations(
    net: pp.pandapowerNet,
    solar_variance_pct: float = 20.0,
    seed: int = 42,
) -> None:
    """Perturb renewable generation and local corridor load based on solar variability."""
    rng = random.Random(seed)
    for idx in net.load.index:
        factor = 1.0 + rng.uniform(-solar_variance_pct, solar_variance_pct) / 100.0
        net.load.at[idx, "p_mw"] = float(net.load.at[idx, "p_mw"]) * factor
