"""API contract and acceptance-level checks (run against the in-process FastAPI app)."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(small_bundle):
    from gridwatch.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def demo(client):
    r = client.post("/api/simulations/demo")
    assert r.status_code == 200
    return r.json()


def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert [s["code"] for s in meta["scenarios"]] == list("ABCDEFG")
    assert "not proof of electricity theft" in meta["warning"]


def test_initial_state_has_network_and_power_flow(client, demo):
    """Acceptance test 1: labelled network and baseline state."""
    topo = client.get(f"/api/simulations/{demo['id']}/topology").json()
    assert len(topo["feeders"]) == 4 and any(b["provenance"] == "public-source" for b in topo["buses"])
    st = client.get(f"/api/simulations/{demo['id']}/state", params={"t": 0}).json()
    assert st["power_flow"]["converged"] is True
    assert st["scenario"]["events"][0]["phase"] == "pending"


def test_timeline_bounds(client, demo):
    """Acceptance test 2: every step is addressable; out-of-range steps are rejected."""
    n = demo["n_steps"]
    assert client.get(f"/api/simulations/{demo['id']}/state", params={"t": n - 1}).status_code == 200
    assert client.get(f"/api/simulations/{demo['id']}/state", params={"t": n}).status_code == 422


def test_energy_balance_matches_state(client, demo):
    """Acceptance test 4: the displayed 24 h balance equals the energy-balance endpoint for the same window."""
    t = 200
    st = client.get(f"/api/simulations/{demo['id']}/state", params={"t": t}).json()
    f2 = next(u for u in st["units"]["feeder"] if u["id"] == "F2")
    eb = client.get(f"/api/simulations/{demo['id']}/energy-balance",
                    params={"kind": "feeder", "id": "F2", "t": t, "start": t - 23, "end": t + 1}).json()
    assert eb["unexplained_kwh"] == pytest.approx(f2["balance_24h"]["unexplained_kwh"], abs=1e-6)
    assert eb["input_kwh"] == pytest.approx(f2["balance_24h"]["input_kwh"], abs=1e-6)


def test_scenario_injection_changes_data(client, demo):
    """Acceptance test 5: the injected scenario changes exactly the affected measurements."""
    diff = client.get(f"/api/simulations/{demo['id']}/baseline-diff", params={"t": 250}).json()
    changed = {c["id"] for c in diff["consumers"]}
    targets = set(demo["events"][0]["consumers"])
    assert changed == targets
    assert all(c["difference_kwh"] < 0 for c in diff["consumers"])


def test_detection_and_explanations(client, demo):
    """Acceptance tests 6-8: detection executes, alerts carry evidence-based explanations and map to the network."""
    r = client.post(f"/api/simulations/{demo['id']}/detect", json={"t": 228})
    assert r.status_code == 200
    res = r.json()
    assert res["n_alerts"] >= 1 and res["detection_id"] > 0
    topo = client.get(f"/api/simulations/{demo['id']}/topology").json()
    feeders = {f["id"] for f in topo["feeders"]}
    for a in res["alerts"]:
        assert a["feeder"] in feeders
        assert a["text"] and a["priority"]["level"] in {"P1", "P2", "P3", "DQ"}
        assert "not proof" in a["text"] or "not a finding" in a["text"]
    hist = client.get("/api/detections", params={"sim_id": demo["id"]}).json()
    assert hist and hist[0]["step"] == 228


def test_compare_methods(client, demo):
    """Acceptance test 9 (scenario level): every method evaluated on the same step."""
    c = client.get(f"/api/simulations/{demo['id']}/compare", params={"t": 228}).json()
    assert len(c["consumer_methods"]) == 7
    assert {"feeder", "dt"} <= set(c["unit_methods"])


def test_replay_is_reproducible(client, demo):
    """Acceptance test 10: same configuration and seed -> identical data and scores."""
    r = client.post(f"/api/simulations/{demo['id']}/replay", params={"t": 150}).json()
    assert r["data_identical"] is True
    assert r["max_abs_score_difference"] <= 1e-12


def test_create_custom_scenario_and_validation(client):
    ok = client.post("/api/simulations", json={"config": {"scenario": "G", "seed": 5, "injections": [
        {"type": "loss_estimate_error", "feeder": "F1", "magnitude": -40, "onset_day": 2, "duration_days": 6}]}})
    assert ok.status_code == 200
    bad = client.post("/api/simulations", json={"config": {"scenario": "B", "seed": 5, "injections": [
        {"type": "sudden_deviation", "feeder": "F9", "magnitude": 40}]}})
    assert bad.status_code == 422
    assert client.get("/api/simulations/does-not-exist").status_code == 404


def test_consumer_and_unit_series(client, demo):
    cid = demo["events"][0]["consumers"][0]
    s = client.get(f"/api/simulations/{demo['id']}/consumers/{cid}/timeseries").json()
    assert len(s["observed_kwh"]) == demo["n_steps"] == len(s["expected_kwh"])
    u = client.get(f"/api/simulations/{demo['id']}/dts/F2-DT1/timeseries", params={"t": 100}).json()
    assert len(u["hourly"]["input"]) == 101
