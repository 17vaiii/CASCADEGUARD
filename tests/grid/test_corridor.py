# OWNER: P1 | STATUS: ACTIVE
"""Unit tests for the Sharavathi corridor model and hydrological limits."""

import pandapower as pp
import pytest

from cascadeguard.grid.corridor_model import build_corridor_network, load_corridor_config
from cascadeguard.grid.hydro import dispatch_hydro, HydroDispatchState
from cascadeguard.grid.seasons import apply_season, load_season_profiles
from cascadeguard.grid.topology_generator import generate_topology_variants


def test_corridor_network_structure():
    net = build_corridor_network()
    # 5 substations + 34 tap buses = 39 buses
    assert len(net.bus) == 39
    # 38 sections * 2 circuits (A and B) = 76 transmission lines
    assert len(net.line) == 76
    assert net.ext_grid.bus.iloc[0] == 0  # Sharavathi is slack bus


def test_corridor_ac_power_flow():
    net = build_corridor_network()
    pp.runpp(net, algorithm="nr", init="dc", max_iteration=50, tolerance_mva=1e-6, numba=False)
    assert net.converged is True
    # Verify voltages are within normal operating bounds [0.95, 1.05]
    assert net.res_bus.vm_pu.min() >= 0.95
    assert net.res_bus.vm_pu.max() <= 1.06


def test_seasonal_profiles_and_application():
    seasons = load_season_profiles()
    assert "monsoon" in seasons
    assert "summer" in seasons
    assert seasons["summer"].corridor_load_scale > seasons["monsoon"].corridor_load_scale

    net = build_corridor_network()
    apply_season(net, seasons["summer"])
    assert net["season_name"] == "summer"
    assert net["season_load_scale"] == seasons["summer"].corridor_load_scale


def test_hydro_dispatch_constraints():
    state = HydroDispatchState(energy_used_mwh=0.0, previous_mw=300.0)
    dispatch, new_state = dispatch_hydro(
        target_mw=500.0,
        season_max_mw=400.0,
        season_min_mw=100.0,
        ramp_limit_mw=50.0,
        daily_energy_limit_mwh=6000.0,
        state=state,
        duration_hours=1.0,
    )
    # Target was 500, but ramp up is limited to 300 + 50 = 350 MW
    assert dispatch.dispatched_mw == 350.0
    assert dispatch.limited_by == "ramp_up"
    assert new_state.energy_used_mwh == 350.0


def test_topology_generator():
    variants = generate_topology_variants(count=3, seed=42)
    assert len(variants) == 3
    for v in variants:
        assert "buses" in v
        assert "tap_spacing_km" in v

