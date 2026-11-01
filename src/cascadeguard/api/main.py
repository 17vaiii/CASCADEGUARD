"""FastAPI service contract for CascadeGuard's local-first platform."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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


@app.post("/api/predict")
def predict(_: DataRequest) -> None:
    _dependency_unavailable("cascade predictor (P3)")


@app.post("/api/screen")
def screen(_: DataRequest) -> None:
    _dependency_unavailable("N-k screening model (P3)")


@app.post("/api/mitigate")
def mitigate(_: DataRequest) -> None:
    _dependency_unavailable("mitigation optimizer (P5)")


@app.post("/api/theft-score")
def theft_score(_: DataRequest) -> None:
    _dependency_unavailable("theft scoring model (P4)")


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
