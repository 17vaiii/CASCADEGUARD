# OWNER: P1 | STATUS: ACTIVE
"""Corridor model builder for the Sharavathi-Bengaluru 220 kV transmission network.

Constructs an AC pandapower network with 39 buses:
  - 5 primary substations: SHARAVATHI (slack), SHIMOGA, SIRA_KBCROSS, NELAMANGALA, PEENYA (Bengaluru load center)
  - 34 virtual tap buses at 10 km intervals
  - 220 kV unfolded dual-circuit lines (Circuit A and Circuit B per 10 km section)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml
import pandapower as pp


def load_corridor_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load corridor configuration dictionary."""
    if config_path is None:
        config_path = Path(__file__).resolve().parents[3] / "configs" / "grids" / "corridor_v0.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        # Sensible defaults matching Sharavathi 220 kV corridor
        return {
            "base_kv": 220,
            "tap_spacing_km": 10,
            "buses": [
                {"id": "SHARAVATHI", "km": 0, "role": "slack_gen"},
                {"id": "SHIMOGA", "km": 110, "role": "junction"},
                {"id": "SIRA_KBCROSS", "km": 215, "role": "junction"},
                {"id": "NELAMANGALA", "km": 320, "role": "junction"},
                {"id": "PEENYA", "km": 361, "role": "load"},
            ],
            "lines": {
                "r_ohm_per_km": 0.020,
                "x_ohm_per_km": 0.18,
                "c_nf_per_km": 20.0,
                "max_i_ka": 1.60,
                "circuits": 2,
            },
            "loads": [
                {"bus": "SHIMOGA", "p_mw": 60, "q_mvar": 20},
                {"bus": "SIRA_KBCROSS", "p_mw": 40, "q_mvar": 12},
                {"bus": "NELAMANGALA", "p_mw": 80, "q_mvar": 25},
                {"bus": "PEENYA", "p_mw": 180, "q_mvar": 60},
            ],
            "shunts": [
                {"bus": "SHIMOGA", "q_mvar_cap": 20},
                {"bus": "SIRA_KBCROSS", "q_mvar_cap": 15},
                {"bus": "NELAMANGALA", "q_mvar_cap": 30},
                {"bus": "PEENYA", "q_mvar_cap": 40},
            ],
            "gen": {"bus": "SHARAVATHI", "vm_pu": 1.05},
        }

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_corridor_network(
    config: dict[str, Any] | None = None,
    load_scale: float = 1.0,
) -> pp.pandapowerNet:
    """Build the unfolded dual-circuit pandapower network for the corridor."""
    if config is None:
        config = load_corridor_config()

    net = pp.create_empty_network(name="Sharavathi_220kV_Corridor")

    base_kv = float(config.get("base_kv", 220))
    tap_spacing = float(config.get("tap_spacing_km", 10))
    substations = config.get("buses", [])
    corridor_len = max(sub["km"] for sub in substations)

    # Compile all bus positions along corridor
    positions: list[tuple[float, str, bool]] = []
    sub_kms = set()
    for sub in substations:
        positions.append((float(sub["km"]), sub["id"], True))
        sub_kms.add(float(sub["km"]))

    km = tap_spacing
    while km < corridor_len:
        if km not in sub_kms:
            positions.append((km, f"TAP_{int(km)}", False))
        km += tap_spacing
    positions.sort(key=lambda x: x[0])

    # Create buses
    name_to_idx: dict[str, int] = {}
    bus_km: dict[int, float] = {}
    for km_val, name, _ in positions:
        idx = pp.create_bus(net, vn_kv=base_kv, name=name)
        bus_km[idx] = km_val
        name_to_idx[name] = idx

    # External grid (Sharavathi generator slack)
    gen_cfg = config.get("gen", {"bus": "SHARAVATHI", "vm_pu": 1.05})
    slack_bus = name_to_idx[gen_cfg["bus"]]
    pp.create_ext_grid(net, bus=slack_bus, vm_pu=float(gen_cfg.get("vm_pu", 1.05)), name=f"GEN_{gen_cfg['bus']}")
    hydro_idx = pp.create_sgen(net, bus=slack_bus, p_mw=0.0, q_mvar=0.0, name="LINGANAMAKKI_HYDRO", in_service=True)

    # Lines: unfolded dual-circuits per section
    line_cfg = config.get("lines", {})
    circuits = int(line_cfg.get("circuits", 2))
    r_per_km = float(line_cfg.get("r_ohm_per_km", 0.020)) * circuits * 2
    x_per_km = float(line_cfg.get("x_ohm_per_km", 0.18)) * circuits * 2
    c_per_km = float(line_cfg.get("c_nf_per_km", 20.0)) / (circuits * 2)
    max_i = float(line_cfg.get("max_i_ka", 1.60)) / (circuits * 2)

    cascade_pairs: dict[int, tuple[int, int]] = {}
    line_section: dict[int, int] = {}
    line_circuit: dict[int, str] = {}
    section_km: dict[int, tuple[float, float]] = {}

    for sec_idx in range(len(positions) - 1):
        km_from, name_from, _ = positions[sec_idx]
        km_to, name_to, _ = positions[sec_idx + 1]
        length = km_to - km_from
        bus_from = name_to_idx[name_from]
        bus_to = name_to_idx[name_to]

        line_a = pp.create_line_from_parameters(
            net, from_bus=bus_from, to_bus=bus_to,
            length_km=length,
            r_ohm_per_km=r_per_km, x_ohm_per_km=x_per_km,
            c_nf_per_km=c_per_km, max_i_ka=max_i,
            name=f"S{sec_idx}_A_{name_from}-{name_to}",
        )
        line_b = pp.create_line_from_parameters(
            net, from_bus=bus_from, to_bus=bus_to,
            length_km=length,
            r_ohm_per_km=r_per_km, x_ohm_per_km=x_per_km,
            c_nf_per_km=c_per_km, max_i_ka=max_i,
            name=f"S{sec_idx}_B_{name_from}-{name_to}",
        )

        cascade_pairs[sec_idx] = (line_a, line_b)
        line_section[line_a] = sec_idx
        line_section[line_b] = sec_idx
        line_circuit[line_a] = "A"
        line_circuit[line_b] = "B"
        section_km[sec_idx] = (km_from, km_to)

    # Loads
    total_load = 0.0
    bus_loads: dict[int, float] = {}
    for lc in config.get("loads", []):
        bus_idx = name_to_idx[lc["bus"]]
        p = float(lc["p_mw"]) * load_scale
        q = float(lc["q_mvar"]) * load_scale
        pp.create_load(net, bus=bus_idx, p_mw=p, q_mvar=q, name=f"LOAD_{lc['bus']}")
        bus_loads[bus_idx] = p
        total_load += p

    # Shunt capacitors
    for sc in config.get("shunts", []):
        bus_idx = name_to_idx[sc["bus"]]
        pp.create_shunt(net, bus=bus_idx, q_mvar=-float(sc["q_mvar_cap"]), name=f"CAP_{sc['bus']}")

    # Store network metadata
    net["cascade_pairs"] = cascade_pairs
    net["line_section"] = line_section
    net["line_circuit"] = line_circuit
    net["section_km"] = section_km
    net["bus_km"] = bus_km
    net["bus_loads_mw"] = bus_loads
    net["total_load_mw"] = total_load
    net["name_to_idx"] = name_to_idx
    net["hydro_sgen_idx"] = hydro_idx

    return net
