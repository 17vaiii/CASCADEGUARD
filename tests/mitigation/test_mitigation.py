# OWNER: P5 | STATUS: ACTIVE
"""R9 / H2 / H3: operating state, hydro bounds, optimizer, greedy baseline and closed-loop verification."""

from __future__ import annotations

import warnings

import pytest

from cascadeguard.mitigation import load_config
from cascadeguard.mitigation.baselines import greedy, no_action
from cascadeguard.mitigation.hydro_redispatch import base_hydro_dispatch, hydro_bounds
from cascadeguard.mitigation.network import Actions, Event, build_state, evaluate_outcome
from cascadeguard.mitigation.optimizer import sensitivities, solve_milp
from cascadeguard.mitigation.verifier import describe_actions, mitigate

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def post_monsoon():
    return build_state("post_monsoon")


@pytest.fixture(scope="module")
def summer():
    return build_state("summer")


def test_states_respect_dispatch_limits(post_monsoon, summer):
    cfg = load_config()
    for st in (post_monsoon, summer):
        assert st.net.res_bus.vm_pu.max() <= 1.0501
        assert cfg["grid_tie"]["min_import_mw"] - 1e-6 <= st.tie_mw <= cfg["grid_tie"]["max_import_mw"] + 1e-6
        assert st.hydro.min_mw <= st.hydro.base_mw <= st.hydro.max_mw
    assert summer.tie_mw > post_monsoon.tie_mw          # summer relies on imports (low reservoir)


def test_hydro_bounds_use_p1_rules():
    from cascadeguard.grid.seasons import load_season_profiles
    cfg = load_config()
    summer = load_season_profiles()["summer"]
    base = base_hydro_dispatch(summer, 500.0, 0.85)
    assert base <= summer.max_generation_mw and base <= summer.daily_energy_limit_mwh / 24
    b = hydro_bounds(summer, base, cfg)
    assert b.max_mw - base <= summer.ramp_rate_mw_per_min * cfg["dispatch"]["response_window_min"] + 1e-6
    cfg["dispatch"]["reservoir_floor_pct"] = 99.0          # H3: reservoir below the floor -> no ramp-up
    assert hydro_bounds(summer, base, cfg).max_mw == pytest.approx(base)


def test_safe_event_needs_no_action(post_monsoon):
    res = mitigate(post_monsoon, Event([70]))
    assert res["stage"] == "no_action_needed" and res["recommendation"]["verified"]


def test_optimizer_prevents_post_monsoon_blackout(post_monsoon):
    ev = Event([0])
    before = no_action(post_monsoon, ev)
    assert before["cascade"] and before["load_lost_pct"] > 90
    res = mitigate(post_monsoon, ev, baseline=before)
    rec = res["recommendation"]
    assert res["stage"] == "optimizer" and rec["verified"]
    assert rec["load_lost_pct"] < 1.0 and rec["n_actions"] <= 2
    assert rec["actions"]["tie_delta_mw"] > 0              # cheapest fix: more import, hydro down
    assert any("import" in line for line in describe_actions(rec["actions"], rec, post_monsoon))


def test_tie_loss_uses_hydro_ramp_then_controlled_shed(summer):
    ev = Event([], True)
    before = no_action(summer, ev)
    assert before["ufls_mw"] > 0 and not before["verified"]
    res = mitigate(summer, ev, baseline=before)
    rec = res["recommendation"]
    assert rec["verified"] and rec["ufls_mw"] == 0
    assert rec["load_lost_pct"] < before["load_lost_pct"]
    assert rec["hydro_mw"] <= summer.hydro.max_mw + 0.5   # H2/H3 bound respected
    assert rec["hydro_delta_mw"] > 1.0                     # hydro ramped up


def test_verifier_rejects_islanding_plans(post_monsoon):
    # Opening both circuits of section 3 islands everything downstream: never "verified".
    out = evaluate_outcome(post_monsoon, Event([0]), Actions(open_lines=[6, 7]))
    assert not out["verified"] and out["cascade_loss_mw"] > 100


def test_unmitigable_event_is_flagged(post_monsoon):
    res = mitigate(post_monsoon, Event([0, 1]))
    assert res["stage"].startswith("unverified") and not res["recommendation"]["verified"]
    text = describe_actions(res["recommendation"]["actions"], res["recommendation"], post_monsoon)
    assert "No verified remedial action" in text[0]


def test_milp_and_greedy_agree_on_simple_case(post_monsoon):
    ev = Event([20])
    sens = sensitivities(post_monsoon, ev, Actions(), max_switch=2)
    assert sens is not None and "tie" in sens.controls
    sol = solve_milp(sens, post_monsoon, 96.0)
    assert sol["status"] in ("optimal", "feasible") and sol["delta"]["tie"] > 0
    g = greedy(post_monsoon, ev)
    assert g["verified"]
