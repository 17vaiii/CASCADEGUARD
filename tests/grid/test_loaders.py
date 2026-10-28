# OWNER: P1 | STATUS: ACTIVE
"""Unit tests for grid loaders and AC power flow convergence (P1-1)."""

import pytest
from cascadeguard.grid.loaders import (
    load_grid,
    run_power_flow,
    validate_base_case_gate,
    SUPPORTED_GRIDS,
)

def test_supported_grids_dict():
    assert "ieee14" in SUPPORTED_GRIDS
    assert "ieee39" in SUPPORTED_GRIDS
    assert "ieee118" in SUPPORTED_GRIDS

def test_load_grid_invalid():
    with pytest.raises(ValueError):
        load_grid("unknown_network")

def test_ieee39_power_flow_converges():
    """Verify that IEEE 39 loads properly and AC power flow converges."""
    net = load_grid("ieee39")
    assert len(net.bus) == 39
    assert len(net.line) > 0
    assert len(net.load) > 0
    
    converged = run_power_flow(net)
    assert converged is True
    assert net.converged is True

    # Validate results exist
    assert "vm_pu" in net.res_bus
    assert "loading_percent" in net.res_line
    assert not net.res_bus["vm_pu"].isna().any()

def test_ieee39_base_case_gate():
    """Verify IEEE 39 passes the base-case validation gate."""
    net = load_grid("ieee39")
    gate = validate_base_case_gate(net, grid_id="ieee39", v_min_limit=0.90, v_max_limit=1.12)
    assert gate.converged is True
    assert gate.passed is True
    assert gate.v_min >= 0.90
    assert gate.v_max <= 1.12
    assert gate.details["bus_count"] == 39

def test_ieee14_convergence():
    """Verify IEEE 14 loads and AC power flow converges."""
    net = load_grid("ieee14")
    assert len(net.bus) == 14
    converged = run_power_flow(net)
    assert converged is True
    assert net.converged is True

def test_ieee118_convergence():
    """Verify IEEE 118 loads and AC power flow converges."""
    net = load_grid("ieee118")
    assert len(net.bus) == 118
    converged = run_power_flow(net)
    assert converged is True
    assert net.converged is True
