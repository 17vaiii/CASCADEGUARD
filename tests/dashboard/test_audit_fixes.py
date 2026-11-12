# OWNER: P5 | STATUS: ACTIVE
"""Regression tests for gaps found in the 2026-11-07 PRD audit (docs/PRD_CHECKLIST_P4_P5.md)."""

from __future__ import annotations

import json
import warnings

import numpy as np
import pytest

from cascadeguard.mitigation import REPO_ROOT
from cascadeguard.mitigation.network import Actions, Event, build_state, evaluate_outcome
from cascadeguard.mitigation.verifier import mitigate
from cascadeguard.retrieval.case_library import CascadeCaseLibrary
from cascadeguard.retrieval.warm_start import warm_mitigate

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def st():
    return build_state("post_monsoon")


@pytest.fixture(scope="module")
def library(st):
    lib = CascadeCaseLibrary("physics")
    for li in (0, 2, 4, 20):
        ev = Event([li])
        lib.add(st, ev, mitigate(st, ev))
    return lib


def test_event_labels_are_plain_ints():
    ev = Event([np.int64(20)])
    assert ev.label == "N-1 [20]" and type(ev.lines[0]) is int
    json.dumps(ev.as_dict())


def test_outcome_has_cascade_path_and_critical_lines(st):
    out = evaluate_outcome(st, Event([0]))
    seq = out["trip_sequence"]
    assert seq[0]["reason"] == "initial" and any(s["reason"] == "overload" for s in seq)
    assert len(out["critical_lines"]) == 5
    assert out["critical_lines"][0]["loading_pct"] >= out["critical_lines"][1]["loading_pct"]
    json.dumps({"s": seq, "c": out["critical_lines"]})


def test_voltage_collapse_counts_as_load_lost(st):
    """A failed AC solve must never read as 'no load lost'."""
    import cascadeguard.sim.cascade_engine as eng
    real = eng.simulate_cascade

    def diverged(net, trips, **kw):
        r = real(net, trips, **kw)
        r.converged = False
        r.load_lost_mw = 0.0
        return r

    eng.simulate_cascade = diverged
    try:
        out = evaluate_outcome(st, Event([70]))
    finally:
        eng.simulate_cascade = real
    assert not out["verified"] and out["cascade"]
    assert out["total_lost_mw"] == pytest.approx(st.total_load_mw)


def test_t9_simulate_counts_collapse():
    from cascadeguard.theft import hidden_load as hl
    import cascadeguard.sim.cascade_engine as eng
    net = hl.corridor_state("post_monsoon")
    real = eng.simulate_cascade

    def diverged(n, trips, **kw):
        r = real(n, trips, **kw)
        r.converged = False
        return r

    eng.simulate_cascade = diverged
    try:
        out = hl._simulate(net, [70])
    finally:
        eng.simulate_cascade = real
    assert out["cascade"] and out["load_lost_mw"] == pytest.approx(net["total_load_mw"])


def test_cases_store_explanations(library):
    case = library.cases[0]
    exp = case["explanation"]
    assert exp["cascade_path"] and exp["critical_lines"] and exp["actions"]


def test_store_vector_projects_without_truncating(library):
    v = library.vectors[0]
    assert len(v) > 128
    out = np.asarray(library.store_vector(v, 128))
    assert len(out) == 128 and np.isclose(np.linalg.norm(out), 1.0)
    # The last features (season, tie loss, island shed) must influence the stored vector.
    changed = v.copy()
    changed[-5:] += 0.5
    assert not np.allclose(library.store_vector(changed, 128), out)
    assert library.store_vector(np.ones(10), 128)[20] == 0.0


def test_load_cases_into_real_qdrant_client(library, monkeypatch, tmp_path):
    """Real qdrant-client (local mode): upsert, then each case finds itself first."""
    from qdrant_client import QdrantClient
    from cascadeguard.retrieval.case_store import QdrantCaseStore
    store = QdrantCaseStore(url="http://localhost:1")
    store.client = QdrantClient(":memory:")
    store.ensure_collections()
    assert library.upsert_to_qdrant(store) == len(library.cases)
    for vec, case in zip(library.vectors, library.cases):
        top = library.query_qdrant(store, vec, 1)
        assert top[0]["payload"]["external_id"] == case["case_id"]
    assert top[0]["payload"]["explanation"]["actions"]


def test_warm_seeded_optimizer_path(st, library):
    res = warm_mitigate(st, Event([6]), library, k=2, try_direct=False)
    assert res["stage"] == "precedent_warm_optimizer" and res["recommendation"]["verified"]


def test_switching_action_is_applied_and_counted(st):
    # Opening one circuit of a section with a surviving partner keeps every load connected.
    out = evaluate_outcome(st, Event([70]), Actions(open_lines=[72]))
    assert out["n_actions"] == 1 and out["actions"]["open_lines"] == [72]
    assert out["cascade_loss_mw"] < 0.5


def test_fallback_demo_data_is_not_gitignored():
    import subprocess
    keep = ["data/processed/theft/inspection_leads.json", "data/processed/theft/feeder_residual_heatmap.parquet",
            "data/processed/mitigation/mitigation_results.parquet", "data/models/theft/theft_bundle.joblib"]
    for path in keep:
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT).returncode == 1, path
    assert subprocess.run(["git", "check-ignore", "-q", "data/processed/theft/dataset/arrays.npz"], cwd=REPO_ROOT).returncode == 0


def test_dashboard_runs_grid_simulation_from_controls():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(REPO_ROOT / "src" / "cascadeguard" / "dashboard" / "app.py"), default_timeout=300)
    at.run()
    trips = next(x for x in at.multiselect if x.label == "Initial line trips (N-k)")
    trips.set_value([0]).run()
    sim_btn = next(b for b in at.button if b.key == "simulation-run-grid")
    sim_btn.click().run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Latest Simulation Run" in text
    assert at.session_state["grid_run_config"]["lines"] == (0,)
    assert at.session_state["shared_grid_result"] is not None
    assert "np.int64" not in text
