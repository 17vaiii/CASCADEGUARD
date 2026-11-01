# OWNER: P1 | STATUS: ACTIVE
"""Unit tests for the AC cascade failure engine and contingency search (P1)."""

import pytest

from cascadeguard.grid.corridor_model import build_corridor_network
from cascadeguard.sim.attack_finder import find_worst_case_attack
from cascadeguard.sim.cascade_engine import simulate_cascade
from cascadeguard.sim.contingency import scan_contingencies
from cascadeguard.sim.islanding import detect_islands, island_has_generation, shed_island_loads
from cascadeguard.sim.weak_link import generate_seasonal_weak_link_report


def test_cascade_engine_n1():
    net = build_corridor_network()
    # Trip line 0
    res = simulate_cascade(net, initial_trips=[0])
    assert res.initial_trips == [0]
    assert res.total_lines_tripped >= 1
    assert res.load_served_mw >= 0.0
    assert res.load_lost_mw >= 0.0
    assert len(res.steps) >= 1


def test_cascade_engine_n2_blackout():
    net = build_corridor_network()
    # Trip both parallel circuits of section 0 (lines 0 and 1)
    res = simulate_cascade(net, initial_trips=[0, 1])
    assert res.total_lines_tripped >= 2
    # Disconnecting the origin generation splits all downstream loads into an unpowered island
    assert res.blackout is True
    assert res.bengaluru_load_lost_mw == 180.0


def test_islanding_and_load_shed():
    net = build_corridor_network()
    islands = detect_islands(net)
    # Healthy grid starts as 1 connected component
    assert len(islands) == 1
    assert island_has_generation(net, islands[0]) is True

    # Manually disconnect section 0
    net.line.at[0, "in_service"] = False
    net.line.at[1, "in_service"] = False
    split_islands = detect_islands(net)
    assert len(split_islands) == 2

    # Island containing Sharavathi has generation; downstream island does not
    has_gen = [island_has_generation(net, isl) for isl in split_islands]
    assert True in has_gen
    assert False in has_gen

    downstream = [isl for isl in split_islands if not island_has_generation(net, isl)][0]
    shed_mw, affected = shed_island_loads(net, downstream)
    assert shed_mw == 360.0  # Sum of all downstream loads (60 + 40 + 80 + 180)


def test_contingency_scanner():
    net = build_corridor_network()
    results = scan_contingencies(net, k=1, limit=5)
    assert len(results) == 5
    # First item has highest load loss
    assert results[0].load_lost_mw >= results[-1].load_lost_mw


def test_attack_finder():
    net = build_corridor_network()
    attack = find_worst_case_attack(net, k_max=2, beam_width=3)
    assert attack["k"] <= 2
    assert len(attack["worst_trips"]) <= 2
    assert attack["load_lost_mw"] > 0.0

