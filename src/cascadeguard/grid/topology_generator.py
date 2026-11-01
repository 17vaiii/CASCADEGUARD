# OWNER: P1 | STATUS: ACTIVE
"""Deterministic synthetic corridor generator for generalization and robustness studies.

Implements P1-6: Generates reproducible 30-60 bus corridor variants.
"""

from __future__ import annotations

from pathlib import Path
import random
from typing import Any
import yaml

from cascadeguard.grid.corridor_model import load_corridor_config, build_corridor_network


def generate_topology_variants(
    count: int = 5,
    seed: int = 42,
    base_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate reproducible 30-60 bus corridor topology configurations."""
    if base_config is None:
        base_config = load_corridor_config()

    rng = random.Random(seed)
    substations = base_config.get("buses", [])
    length = max(b["km"] for b in substations)

    variants = []
    attempts = 0
    while len(variants) < count and attempts < 100:
        attempts += 1
        spacing = rng.uniform(7.5, 12.5)
        var = dict(base_config)
        var["tap_spacing_km"] = round(spacing, 2)

        lines = dict(base_config.get("lines", {}))
        lines["r_ohm_per_km"] = round(lines.get("r_ohm_per_km", 0.02) * rng.uniform(0.9, 1.1), 4)
        lines["x_ohm_per_km"] = round(lines.get("x_ohm_per_km", 0.18) * rng.uniform(0.9, 1.1), 4)
        var["lines"] = lines

        # Approximate bus count
        n_buses = len(substations) + int(length / spacing)
        if 30 <= n_buses <= 60:
            variants.append(var)

    return variants
