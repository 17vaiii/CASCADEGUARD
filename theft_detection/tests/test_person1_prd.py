"""Acceptance coverage for PRD Person 1 simulation deliverables."""
import pytest


def test_ieee_benchmarks_converge():
    from grid.benchmarks import run_ieee_benchmarks
    results = run_ieee_benchmarks()
    assert [r.case for r in results] == ["case14", "case39", "case118"]
    assert all(r.converged and r.losses_mw >= 0 for r in results)


def test_daily_hydro_obeys_energy_ramp_and_storage():
    from grid.hydro import get_season, load_hydro_config, simulate_hydro_day
    season = get_season("summer")
    result = simulate_hydro_day([350.0] * 24, season)
    assert result.total_generation_mwh <= season.daily_energy_limit_mwh + 1e-6
    assert all(x.dispatched_mw <= season.max_generation_mw for x in result.intervals)
    assert all(x.reservoir_mcm >= load_hydro_config().reservoir.min_operating_mcm
               for x in result.intervals)
    ramp = season.ramp_rate_mw_per_min * 60
    assert all(abs(b.dispatched_mw-a.dispatched_mw) <= ramp + 1e-6
               for a, b in zip(result.intervals, result.intervals[1:]))


def test_synthetic_corridor_variants_build_with_30_to_60_buses():
    from grid.build import build_net
    from grid.topology_variants import generate_topology_variants
    variants = generate_topology_variants(3, seed=91)
    assert len(variants) == 3
    counts = [len(build_net(topology=v).bus) for v in variants]
    assert all(30 <= count <= 60 for count in counts)
    assert variants[0].model_dump() == generate_topology_variants(3, seed=91)[0].model_dump()


def test_weather_and_renewable_overlays_are_available():
    from grid.cascade import build_cascade_net
    from grid.renewables import apply_renewable_scenario, renewable_profile
    from grid.weather import WEATHER_SCENARIOS, line_outage_probabilities
    net = build_cascade_net()
    probabilities = line_outage_probabilities(net, "monsoon_storm")
    assert len(probabilities) == len(net.line)
    assert all(0 <= p <= 1 for p in probabilities.values())
    scenario = renewable_profile("summer", 12)
    ids = apply_renewable_scenario(net, scenario)
    assert len(ids) == 2 and net.renewable_generation_mw > 0
    assert "monsoon_storm" in WEATHER_SCENARIOS


def test_cascade_engine_trips_line_and_returns_trace():
    from grid.cascade import build_cascade_net, simulate_cascade
    net = build_cascade_net()
    result = simulate_cascade(net, [int(net.line.index[0])])
    assert result.initial_trips
    assert result.steps
    assert result.total_lines_tripped >= 1


def test_gnn_guidance_candidates_are_simulator_verified():
    from grid.attack_finder import gnn_guided_search
    from grid.cascade import build_cascade_net
    net = build_cascade_net()
    results = gnn_guided_search(net, lambda _net, trips: float(sum(trips)),
                                k=1, beam_width=1, verify_top_n=1)
    assert len(results) == 1
    assert results[0].verified and results[0].cascade is not None
    assert results[0].predicted_score is not None


def test_scenario_rows_expose_pre_event_graph_features_without_state_leakage():
    from grid.config import load_topology
    from simdata.cascade_scenarios import _run_contingency
    row = _run_contingency(([0], "monsoon", 1.0, 1, load_topology(), 42))
    assert row is not None
    assert row["graph_feature_schema"] == "cascade_graph_v1"
    assert row["graph_feature_timing"] == "pre_contingency"
    assert len(row["pre_bus_vm_pu"]) == len(row["bus_ids"]) == 39
    assert len(row["pre_bus_p_mw"]) == len(row["pre_bus_q_mvar"]) == 39
    assert len(row["pre_line_loading_pct"]) == len(row["line_ids"]) == 76
    assert len(row["pre_line_r_ohm"]) == len(row["pre_line_x_ohm"]) == 76
    # The tripped line has no final-state loading; its intact baseline loading
    # remains present as an explicit pre-event feature.
    assert row["line_0_loading"] is None or row["line_0_loading"] != row["line_0_loading"]
    assert row["pre_line_loading_pct"][0] >= 0
