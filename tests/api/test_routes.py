# OWNER: P2 | STATUS: ACTIVE
"""Integration tests for CascadeGuard FastAPI platform routes."""

import pytest
from fastapi.testclient import TestClient

from cascadeguard.api.main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "storage_mode": "local"}


def test_audit_workflow(tmp_path, monkeypatch):
    import cascadeguard.api.audit as audit_module
    monkeypatch.setattr(audit_module, "DEFAULT_DB", tmp_path / "audit.sqlite3")

    # 1. Create audit
    req = {
        "recommendation": {"action": "trip_line_10", "reason": "overcurrent_prevent"},
        "data_refs": ["scenario_test_01"],
        "data_fingerprint": "abc123sha",
    }
    create_res = client.post("/api/audit/recommendations", json=req)
    assert create_res.status_code == 201
    audit_data = create_res.json()
    audit_id = audit_data["audit_id"]
    assert audit_id is not None

    # 2. Read audit
    read_res = client.get(f"/api/audit/recommendations/{audit_id}")
    assert read_res.status_code == 200
    assert read_res.json()["data_fingerprint"] == "abc123sha"

    # 3. Verify audit
    v_req = {"verified": True, "outcome": "cascade_arrested", "details": {"shed_mw": 0.0}}
    v_res = client.post(f"/api/audit/recommendations/{audit_id}/verification", json=v_req)
    assert v_res.status_code == 200
    assert v_res.json()["verification"]["outcome"] == "cascade_arrested"


def test_unregistered_p4_p5_routes_return_503():
    # P5 registered its optimizer: an empty request is a 400; 503 only if OR-Tools is missing.
    res_mit = client.post("/api/mitigate", json={})
    assert res_mit.status_code in (400, 503)
    if res_mit.status_code == 503:
        assert res_mit.json()["detail"]["component"] == "mitigation optimizer (P5)"

    # P4 registered its scorer: 503 only while the trained bundle is absent; with the bundle,
    # an empty request is a 400 (no meter readings supplied).
    res_theft = client.post("/api/theft-score", json={})
    assert res_theft.status_code in (400, 503)
    if res_theft.status_code == 503:
        assert res_theft.json()["detail"]["component"] == "theft scoring model (P4)"


def test_predict_and_screen_with_sample_snapshot():
    snapshot = {
        "scenario_id": "test_grid_case",
        "bus_ids": [f"bus_{i}" for i in range(5)],
        "pre_bus_vm_pu": [1.02, 1.01, 1.00, 0.99, 1.01],
        "pre_bus_p_mw": [150.0, -30.0, -40.0, -40.0, -40.0],
        "pre_bus_q_mvar": [20.0, -5.0, -5.0, -5.0, -5.0],
        "line_ids": [f"line_{i}" for i in range(4)],
        "line_from_bus": [0, 1, 2, 3],
        "line_to_bus": [1, 2, 3, 4],
        "pre_line_r_ohm": [0.4, 0.4, 0.4, 0.4],
        "pre_line_x_ohm": [2.0, 2.0, 2.0, 2.0],
        "pre_line_loading_pct": [60.0, 70.0, 80.0, 85.0],
        "initial_trips": [1],
    }

    # Predict endpoint
    pred_res = client.post("/api/predict", json={"snapshot": snapshot})
    assert pred_res.status_code == 200
    pred = pred_res.json()
    assert "predicted_cascade_size" in pred
    assert "predicted_load_lost_mw" in pred
    assert "line_failure_probabilities" in pred
    assert "confidence" in pred
    assert pred["confidence"]["conformal_coverage"] == 0.90

    # Screen endpoint
    screen_res = client.post("/api/screen", json={
        "snapshot": snapshot,
        "options": {"candidate_trips": [[0], [1], [2]], "top_k": 2}
    })
    assert screen_res.status_code == 200
    screen = screen_res.json()
    assert screen["total_screened"] == 3
    assert len(screen["top_contingencies"]) == 2

