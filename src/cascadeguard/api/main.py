# OWNER: P2 | STATUS: ACTIVE
"""FastAPI service contract for CascadeGuard's local-first platform."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import numpy as np
import torch

from cascadeguard.api.audit import create_recommendation, get_audit, record_verification

app = FastAPI(
    title="CascadeGuard API",
    version="0.1.0",
    description=("Simulation and decision-support API. Recommendations are advisory; "
                 "they require operator review and simulator verification."),
)


class DataRequest(BaseModel):
    request_id: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)
    scenario_ids: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class RecommendationAuditRequest(BaseModel):
    recommendation: dict[str, Any] | list[Any] | str
    data_refs: list[str] = Field(default_factory=list)
    data_fingerprint: str | None = None


class VerificationRequest(BaseModel):
    verified: bool
    outcome: str
    details: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage_mode": "local"}


def _dependency_unavailable(component: str) -> None:
    raise HTTPException(
        status_code=503,
        detail={"code": "dependency_not_ready", "component": component,
                "message": f"{component} is not registered yet; the endpoint contract is available."},
    )


@lru_cache(maxsize=1)
def _load_p3_model() -> tuple[Any, float, float] | None:
    """Load CascadeGNN model and calibration parameters if trained."""
    checkpoint_path = Path("data/models/cascade_gnn.pt")
    if not checkpoint_path.exists():
        return None
    try:
        from cascadeguard.cascade_ml.gnn import CascadeGNN
        device = "cpu"
        model = CascadeGNN().to(device)
        ckpt = torch.load(checkpoint_path, map_location=device, weights_only=True)
        model.load_state_dict(ckpt.get("model_state", ckpt))
        model.eval()
        temperature = float(ckpt.get("temperature", 1.0))
        conformal_q = float(ckpt.get("conformal_q", 10.0))
        return model, temperature, conformal_q
    except Exception:
        return None


@app.post("/api/predict")
def predict(req: DataRequest) -> dict[str, Any]:
    p3_res = _load_p3_model()
    if p3_res is None:
        _dependency_unavailable("cascade predictor (P3)")

    model, temperature, conformal_q = p3_res
    if not req.snapshot:
        raise HTTPException(status_code=400, detail="Missing required 'snapshot' object in request body")

    try:
        from cascadeguard.cascade_ml.graph_builder import build_graph
        from cascadeguard.cascade_ml.explain import CascadeExplainer

        g = build_graph(req.snapshot, include_targets=False)
        with torch.no_grad():
            out = model(
                x=g.x,
                edge_index=g.edge_index,
                edge_attr=g.edge_attr,
                line_from=g.edge_index[0, :g.num_lines],
                line_to=g.edge_index[1, :g.num_lines],
                line_features=g.line_features,
            )

        line_logits = out["line_logits"].cpu().numpy()
        calibrated_probs = 1.0 / (1.0 + np.exp(-line_logits / max(temperature, 1e-4)))

        pred_loss = float(out["load_loss_mw"].item())
        pred_size = float(out["cascade_size"].item())
        has_casc_prob = float(out["has_cascade_prob"].item())

        lower_loss = max(0.0, pred_loss - conformal_q)
        upper_loss = pred_loss + conformal_q

        line_probs_dict = {
            f"line_{i}": round(float(calibrated_probs[i]), 4)
            for i in range(len(calibrated_probs))
        }

        # Explain top critical lines
        explainer = CascadeExplainer(model)
        explanation = explainer.explain_scenario(g, top_k_lines=5)

        return {
            "scenario_id": req.snapshot.get("scenario_id", "live_query"),
            "predicted_cascade_size": round(pred_size, 2),
            "predicted_load_lost_mw": round(pred_loss, 2),
            "load_loss_conformal_interval": [round(lower_loss, 2), round(upper_loss, 2)],
            "has_cascade_prob": round(has_casc_prob, 4),
            "line_failure_probabilities": line_probs_dict,
            "critical_lines": explanation["critical_propagation_lines"],
            "confidence": {
                "conformal_coverage": 0.90,
                "temperature": round(temperature, 4),
            },
            "model_version": "cascade_gnn_v1",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@app.post("/api/screen")
def screen(req: DataRequest) -> dict[str, Any]:
    p3_res = _load_p3_model()
    if p3_res is None:
        _dependency_unavailable("N-k screening model (P3)")

    model, _, _ = p3_res
    if not req.snapshot:
        raise HTTPException(status_code=400, detail="Missing required 'snapshot' object in request body")

    try:
        from cascadeguard.cascade_ml.screening import ContingencyScreener
        screener = ContingencyScreener(model)
        candidate_trips = req.options.get("candidate_trips")
        if not candidate_trips:
            # Default to screening all N-1 single outages
            num_lines = len(req.snapshot.get("line_from_bus") or range(76))
            candidate_trips = [[i] for i in range(num_lines)]

        top_k = int(req.options.get("top_k", 10))
        res = screener.screen_contingencies(req.snapshot, candidate_trips, top_k=top_k)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screening failed: {str(e)}")


@app.post("/api/mitigate")
def mitigate(req: DataRequest) -> dict[str, Any]:
    """P5 verified minimal mitigation. ``snapshot`` = {season, lines: [int], tie_loss: bool,
    theft_aware: bool, intensity: float}; ``options.brief`` adds the cited copilot brief.

    Advisory only; every response is written to the audit log with its verification result.
    """
    try:
        from cascadeguard.mitigation.service import mitigation_request
    except ImportError:
        _dependency_unavailable("mitigation optimizer (P5)")
    if not req.snapshot.get("season"):
        raise HTTPException(status_code=400, detail="snapshot.season and snapshot.lines / tie_loss are required")
    try:
        result = mitigation_request(req.snapshot, bool(req.options.get("brief", False)))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rec = result["recommendation"]
    audit = create_recommendation(
        {"kind": "corridor_mitigation", "event": result["event"], "stage": result["stage"],
         "actions": rec["actions"], "verified": rec["verified"]},
        [result["event"]["label"], result["season"]])
    record_verification(audit["audit_id"], {"verified": bool(rec["verified"]), "outcome": result["stage"],
                                            "details": {"load_lost_pct": rec["load_lost_pct"]}})
    return {**result, "audit_id": audit["audit_id"]}


@app.post("/api/theft-score")
def theft_score(req: DataRequest) -> dict[str, Any]:
    """P4 theft leads. ``snapshot`` = {readings, history_end, tamper_events?}; ``options.top_k``.

    Leads are advisory and require field inspection; each response is written to the audit log
    (consumer IDs and a payload fingerprint only, never raw meter reads).
    """
    from cascadeguard.theft.service import BundleMissing, load_bundle, score_consumers
    try:
        load_bundle()
    except BundleMissing:
        _dependency_unavailable("theft scoring model (P4)")
    if not req.snapshot.get("readings"):
        raise HTTPException(status_code=400, detail="snapshot.readings (interval meter rows) is required")
    try:
        result = score_consumers({**req.snapshot, "top_k": req.options.get("top_k", req.snapshot.get("top_k", 20))})
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    import hashlib
    import json as _json
    fingerprint = "sha256:" + hashlib.sha256(_json.dumps(req.snapshot, sort_keys=True, default=str)
                                             .encode("utf-8")).hexdigest()
    audit = create_recommendation(
        {"kind": "theft_inspection_leads", "model_version": result["model_version"],
         "leads": [{"consumer_id": lead["consumer_id"], "score": lead["score"],
                    "confidence": lead["confidence"]} for lead in result["leads"]]},
        [lead["consumer_id"] for lead in result["leads"]], fingerprint)
    return {**result, "audit_id": audit.get("audit_id")}


@app.post("/api/audit/recommendations", status_code=201)
def audit_recommendation(request: RecommendationAuditRequest) -> dict[str, Any]:
    return create_recommendation(request.recommendation, request.data_refs,
                                 request.data_fingerprint)


@app.post("/api/audit/recommendations/{audit_id}/verification")
def verify_recommendation(audit_id: str, request: VerificationRequest) -> dict[str, Any]:
    result = record_verification(audit_id, request.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail="audit record not found")
    return result


@app.get("/api/audit/recommendations/{audit_id}")
def read_audit_record(audit_id: str) -> dict[str, Any]:
    result = get_audit(audit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="audit record not found")
    return result
