"""Deterministic synthetic corridor variants for topology generalization."""
from __future__ import annotations

from pathlib import Path
import random

import yaml

from grid.config import TopologyConfig, load_topology


def generate_topology_variants(count: int = 10, *, seed: int = 17,
                               base: TopologyConfig | None = None) -> list[TopologyConfig]:
    """Create reproducible 30–60 bus corridor-like synthetic networks.

    These vary tap spacing and line parameters around the assumed base model;
    they are synthetic training/robustness cases, not field topology claims.
    """
    if count < 1:
        raise ValueError("count must be positive")
    topology = base or load_topology()
    rng = random.Random(seed)
    length = max(b.km for b in topology.buses)
    variants: list[TopologyConfig] = []
    for _ in range(count):
        spacing = rng.uniform(8.0, 15.0)
        buses = [b.model_dump() for b in topology.buses]
        lines = topology.lines.model_dump()
        lines["r_ohm_per_km"] *= rng.uniform(0.85, 1.15)
        lines["x_ohm_per_km"] *= rng.uniform(0.85, 1.15)
        raw = topology.model_dump()
        raw.update(tap_spacing_km=spacing, buses=buses, lines=lines)
        variant = TopologyConfig.model_validate(raw)
        n = len(variant.buses) + sum(1 for km in range(1, int(length / spacing) + 1)
                                     if km * spacing < length and
                                     all(abs(km * spacing - b.km) > .1 for b in variant.buses))
        if 30 <= n <= 60:
            variants.append(variant)
    return variants


def write_topology_variants(out_dir: str | Path = "data/synthetic/topologies",
                            count: int = 10, *, seed: int = 17) -> list[Path]:
    """Write generated configs as YAML files and return their paths."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, topology in enumerate(generate_topology_variants(count, seed=seed), 1):
        path = root / f"corridor_variant_{index:03d}.yaml"
        path.write_text(yaml.safe_dump(topology.model_dump(), sort_keys=False), encoding="utf-8")
        paths.append(path)
    return paths
