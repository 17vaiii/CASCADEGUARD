# OWNER: P4 | STATUS: ACTIVE
"""`POST /api/theft-score` with the trained P4 bundle (skipped until the pipeline has run)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cascadeguard.theft.service import BUNDLE_PATH

pytestmark = pytest.mark.skipif(not BUNDLE_PATH.exists(),
                                reason="run `python -m cascadeguard.theft.pipeline` to train the P4 bundle")


def test_theft_score_route_returns_audited_leads(ds, tmp_path, monkeypatch):
    import cascadeguard.api.audit as audit
    from cascadeguard.api.main import app
    monkeypatch.setattr(audit, "DEFAULT_DB", tmp_path / "audit.sqlite3")
    client = TestClient(app)
    frame = ds.to_meter_frame(ds.consumers.consumer_id.head(10).tolist())
    rows = (frame[["timestamp", "consumer_id", "feeder_id", "consumer_type", "metered_kwh"]]
            .assign(timestamp=frame.timestamp.astype(str)).to_dict(orient="records"))
    res = client.post("/api/theft-score", json={
        "snapshot": {"readings": rows, "history_end": str(ds.timestamps[ds.history_end])},
        "options": {"top_k": 3}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["leads"]) == 3 and body["requires_human_inspection"]
    rec = client.get(f"/api/audit/recommendations/{body['audit_id']}")
    assert rec.status_code == 200
    assert rec.json()["recommendation"]["kind"] == "theft_inspection_leads"
    assert client.post("/api/theft-score", json={"snapshot": {}}).status_code == 400
