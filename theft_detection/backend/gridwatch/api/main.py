"""FastAPI application: REST API + (optionally) the built frontend.

Run:  uvicorn gridwatch.api.main:app --port 8000
Docs: http://localhost:8000/docs (OpenAPI, generated from the endpoint signatures below)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import DB_PATH, FRONTEND_DIST, RESULTS_DIR, STEP_HOURS
from ..detection.methods import CONSUMER_METHODS, UNIT_METHODS
from ..energy_balance.balance import UNEXPLAINED_WARNING
from ..energy_balance.loss_model import LOSS_MODEL_REL_SD
from ..engine import DEFAULT_CONSUMER_METHOD, DEFAULT_UNIT_METHOD, SimulationRun
from ..features.build import FEATURE_DESCRIPTIONS, RuleConfig
from ..pipeline import load_or_train_bundle, prepare
from ..provenance import provenance
from ..simulation.generator import generate
from ..simulation.scenarios import SCENARIO_CATALOG, SimulationConfig, demo_config
from ..storage import Store

log = logging.getLogger("gridwatch.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ConsumerMethod = Literal[tuple(CONSUMER_METHODS)]  # type: ignore[valid-type]
UnitMethod = Literal[tuple(UNIT_METHODS)]  # type: ignore[valid-type]
MAX_LIVE_RUNS = 6


class RulesModel(BaseModel):
    consumer_shortfall: float = Field(0.35, ge=0.05, le=0.95)
    min_completeness: float = Field(0.80, ge=0.0, le=1.0)
    balance_ratio: float = Field(0.03, ge=0.0, le=0.5)
    balance_z: float = Field(2.0, ge=0.5, le=10.0)
    combined_dt_z: float = Field(2.0, ge=0.5, le=10.0)


class CreateSimulation(BaseModel):
    config: SimulationConfig
    rules: RulesModel | None = None


class DetectRequest(BaseModel):
    t: int = Field(ge=0)
    consumer_method: ConsumerMethod = DEFAULT_CONSUMER_METHOD  # type: ignore[valid-type]
    unit_method: UnitMethod = DEFAULT_UNIT_METHOD  # type: ignore[valid-type]


class AppState:
    def __init__(self):
        self.bundle = None
        self.store: Store | None = None
        self.runs: OrderedDict[str, SimulationRun] = OrderedDict()
        self.twins: dict[str, object] = {}
        self.lock = threading.Lock()

    def add(self, run: SimulationRun) -> None:
        with self.lock:
            self.runs[run.id] = run
            while len(self.runs) > MAX_LIVE_RUNS:
                _, old = self.runs.popitem(last=False)
                old.stop()
                self.twins.pop(old.id, None)

    def get(self, sim_id: str) -> SimulationRun:
        with self.lock:
            run = self.runs.get(sim_id)
            if run is not None:
                self.runs.move_to_end(sim_id)
                return run
        rec = self.store.get_simulation(sim_id) if self.store else None
        if rec is None:
            raise HTTPException(404, f"simulation {sim_id} not found")
        # Evicted from memory: rebuild deterministically from the stored configuration.
        rules = RuleConfig(**rec["rules"]) if rec["rules"] else None
        run = SimulationRun(SimulationConfig(**rec["config"]), self.bundle, run_id=sim_id, rules=rules)
        if run.d.data_hash != rec["data_hash"]:
            log.error("regenerated data hash mismatch for %s", sim_id)
        self.add(run)
        return run


S = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    S.store = Store(DB_PATH)
    S.bundle = load_or_train_bundle()
    log.info("GridWatch API ready (models trained %s)", S.bundle.meta.get("trained_at"))
    yield
    for r in S.runs.values():
        r.stop()


app = FastAPI(
    title="Sharavathi GridWatch API",
    version=__version__,
    description="Grid digital twin and AI-assisted electricity-theft *risk screening* on synthetic data. "
                "All measurements are simulated; alerts are investigation signals, not findings of theft.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": f"not found: {exc}"})


def _clean(obj):
    """Make numpy scalars / NaN JSON-safe."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if np.isfinite(f) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    return obj


# ---------------------------------------------------------------------------------- meta
@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "version": __version__, "models_loaded": S.bundle is not None,
            "live_runs": len(S.runs)}


@app.get("/api/meta", tags=["meta"])
def meta():
    """Scenario catalogue, parameter limits, detection methods, rules, units and the demo preset."""
    schema = SimulationConfig.model_json_schema()
    return _clean({
        "version": __version__,
        "scenarios": SCENARIO_CATALOG,
        "config_schema": schema,
        "injection_schema": schema.get("$defs", {}).get("Injection"),
        "demo_config": demo_config().model_dump(),
        "consumer_methods": CONSUMER_METHODS,
        "unit_methods": UNIT_METHODS,
        "default_methods": {"consumer": DEFAULT_CONSUMER_METHOD, "unit": DEFAULT_UNIT_METHOD},
        "rules_default": asdict(RuleConfig()),
        "rules_schema": RulesModel.model_json_schema(),
        "thresholds": {k: v for k, v in S.bundle.thresholds.items()},
        "feature_descriptions": FEATURE_DESCRIPTIONS,
        "timeline": {"step_hours": STEP_HOURS, "measurement_unit": "kWh per hourly interval",
                     "power_flow": "pandapower AC Newton-Raphson snapshot solved for the hourly-average demand of "
                                   "the displayed step"},
        "loss_model_rel_sd": LOSS_MODEL_REL_SD,
        "warning": UNEXPLAINED_WARNING,
        "model_meta": {k: v for k, v in S.bundle.meta.items() if k != "feature_sets"},
    })


@app.get("/api/provenance", tags=["meta"])
def get_provenance():
    """Verified facts with sources, unverified items, modelling assumptions, synthetic elements, ethics."""
    return provenance()


@app.get("/api/models", tags=["meta"])
def models():
    return _clean({"meta": S.bundle.meta, "thresholds": S.bundle.thresholds})


# --------------------------------------------------------------------------- simulations
def _create(config: SimulationConfig, rules: RulesModel | None) -> dict:
    rc = RuleConfig(**rules.model_dump()) if rules else None
    run = SimulationRun(config, S.bundle, rules=rc)
    S.add(run)
    summary = run.summary()
    S.store.save_simulation(run.id, config.model_dump(), rules.model_dump() if rules else None,
                            run.d.data_hash, summary)
    return _clean(summary)


@app.post("/api/simulations", tags=["simulation"])
def create_simulation(req: CreateSimulation):
    """Generate a simulation run from a scenario configuration (deterministic for a given seed)."""
    return _create(req.config, req.rules)


@app.post("/api/simulations/demo", tags=["simulation"])
def create_demo():
    """The pre-configured faculty demonstration scenario (same code path as any other run)."""
    return _create(demo_config(), None)


@app.get("/api/simulations", tags=["simulation"])
def list_simulations(limit: int = Query(30, ge=1, le=200)):
    return S.store.list_simulations(limit)


@app.get("/api/simulations/{sim_id}", tags=["simulation"])
def get_simulation(sim_id: str):
    return _clean(S.get(sim_id).summary())


@app.get("/api/simulations/{sim_id}/topology", tags=["network"])
def topology(sim_id: str):
    return S.get(sim_id).topology()


@app.get("/api/simulations/{sim_id}/state", tags=["network"])
def state(sim_id: str, t: int = Query(..., ge=0), consumer_method: ConsumerMethod = DEFAULT_CONSUMER_METHOD,  # type: ignore[valid-type]
          unit_method: UnitMethod = DEFAULT_UNIT_METHOD):  # type: ignore[valid-type]
    """Network state at timeline step t: power-flow snapshot, energy balances, scores and event status."""
    return _clean(S.get(sim_id).state(t, consumer_method, unit_method))


@app.get("/api/simulations/{sim_id}/alerts", tags=["detection"])
def alerts(sim_id: str, t: int = Query(..., ge=0), consumer_method: ConsumerMethod = DEFAULT_CONSUMER_METHOD,  # type: ignore[valid-type]
           unit_method: UnitMethod = DEFAULT_UNIT_METHOD, limit: int = Query(40, ge=1, le=500)):  # type: ignore[valid-type]
    return _clean(S.get(sim_id).alerts(t, consumer_method, unit_method, limit))


@app.post("/api/simulations/{sim_id}/detect", tags=["detection"])
def detect(sim_id: str, req: DetectRequest):
    """Execute the selected detectors at step t, generate explanations and record the run."""
    run = S.get(sim_id)
    t0 = time.perf_counter()
    run._eval_cache.pop(req.t, None)  # force the models to execute now
    res = run.alerts(req.t, req.consumer_method, req.unit_method, limit=500)
    ms = (time.perf_counter() - t0) * 1000.0
    res["compute_ms"] = round(ms, 1)
    res["detection_id"] = S.store.save_detection(
        sim_id, req.t, req.consumer_method, req.unit_method, res["n_alerts"], ms,
        {"alerts": [{k: a[k] for k in ("kind", "id", "score", "threshold", "priority")} for a in res["alerts"]]})
    return _clean(res)


@app.get("/api/simulations/{sim_id}/compare", tags=["detection"])
def compare(sim_id: str, t: int = Query(..., ge=0)):
    """All methods on the same scenario and step, against simulation ground truth."""
    return _clean(S.get(sim_id).compare(t))


@app.get("/api/simulations/{sim_id}/energy-balance", tags=["energy"])
def energy_balance(sim_id: str, kind: Literal["feeder", "dt"], id: str, t: int = Query(..., ge=0),
                   start: int = Query(..., ge=0), end: int = Query(..., ge=1)):
    """Energy balance for one boundary over steps [start, end), using data available at step t."""
    run = S.get(sim_id)
    if end <= start:
        raise HTTPException(422, "end must be greater than start")
    if end > run.d.n_steps:
        raise HTTPException(422, f"end must be <= {run.d.n_steps}")
    h0 = run.d.h0
    res = run.ctx.accountant.balance(kind, id, h0 + start, h0 + end, run.tau(t))
    res["window"]["start_step"], res["window"]["end_step"], res["window"]["as_of_step"] = start, end, t
    res["formula"] = ("U = E_in - E_metered - E_imputed - L_est  [kWh]; sigma from input-meter, consumer-meter, "
                      "loss-model and imputation uncertainty")
    res["boundary"]["description"] = (
        "Feeder boundary: feeder-head meter at the 11 kV substation bay to all consumer meters on the feeder "
        "(includes 11 kV line, DT and LV losses)." if kind == "feeder" else
        "DT boundary: DT meter on the LV side of the transformer to the consumer meters it supplies "
        "(includes LV network losses only).")
    return _clean(res)


@app.get("/api/simulations/{sim_id}/feeders/{fid}/timeseries", tags=["energy"])
def feeder_series(sim_id: str, fid: str, t: int = Query(..., ge=0)):
    return _clean(S.get(sim_id).unit_series("feeder", fid, t))


@app.get("/api/simulations/{sim_id}/dts/{dt}/timeseries", tags=["energy"])
def dt_series(sim_id: str, dt: str, t: int = Query(..., ge=0)):
    return _clean(S.get(sim_id).unit_series("dt", dt, t))


@app.get("/api/simulations/{sim_id}/consumers", tags=["investigation"])
def consumers(sim_id: str, t: int = Query(..., ge=0), feeder: str | None = None, dt: str | None = None,
              method: ConsumerMethod = DEFAULT_CONSUMER_METHOD):  # type: ignore[valid-type]
    return _clean(S.get(sim_id).consumers_table(t, feeder, dt, method))


@app.get("/api/simulations/{sim_id}/consumers/{cid}/timeseries", tags=["investigation"])
def consumer_series(sim_id: str, cid: str):
    return _clean(S.get(sim_id).consumer_series(cid))


@app.get("/api/simulations/{sim_id}/baseline-diff", tags=["simulation"])
def baseline_diff(sim_id: str, t: int = Query(..., ge=0)):
    """Which measurements differ from the same seed under normal operation (Scenario A), up to step t."""
    run = S.get(sim_id)
    d = run.d
    if run.id not in S.twins:
        twin_cfg = run.config.model_copy(update={"scenario": "A", "injections": [], "label": None})
        S.twins[run.id] = generate(twin_cfg)
    tw = S.twins[run.id]
    h = run.tau(t)
    sl = slice(d.h0, h + 1)
    out = {"t": t, "consumers": [], "dt_meters": [], "feeder_meters": []}
    a, b = np.nan_to_num(d.meter_kwh[:, sl]), np.nan_to_num(tw.meter_kwh[:, sl])
    miss_a, miss_b = ~np.isfinite(d.meter_kwh[:, sl]), ~np.isfinite(tw.meter_kwh[:, sl])
    delay_a = (d.arrival_delay[:, sl] > 1) & np.isfinite(d.arrival_delay[:, sl])
    delay_b = (tw.arrival_delay[:, sl] > 1) & np.isfinite(tw.arrival_delay[:, sl])
    for i in np.flatnonzero((np.abs(a - b).sum(axis=1) > 1e-6) | (miss_a != miss_b).any(axis=1)
                            | (delay_a != delay_b).any(axis=1)):
        out["consumers"].append({
            "id": str(d.consumer_ids[i]), "scenario_kwh": float(a[i].sum()), "normal_kwh": float(b[i].sum()),
            "difference_kwh": float(a[i].sum() - b[i].sum()),
            "extra_missing_readings": int(miss_a[i].sum() - miss_b[i].sum()),
            "extra_delayed_readings": int(delay_a[i].sum() - delay_b[i].sum())})
    for key, ids, arr_a, arr_b in (("dt_meters", d.dt_ids, d.dt_meter_kwh, tw.dt_meter_kwh),
                                   ("feeder_meters", d.feeder_ids, d.feeder_meter_kwh, tw.feeder_meter_kwh)):
        da, db = np.nansum(arr_a[:, sl], axis=1), np.nansum(arr_b[:, sl], axis=1)
        for j in np.flatnonzero(np.abs(da - db) > 1e-6):
            out[key].append({"id": ids[j], "scenario_kwh": float(da[j]), "normal_kwh": float(db[j]),
                             "difference_kwh": float(da[j] - db[j])})
    out["loss_estimate_factor_changed"] = [d.feeder_ids[f] for f in range(len(d.feeder_ids))
                                           if not np.allclose(d.loss_estimate_factor[f, sl], tw.loss_estimate_factor[f, sl])]
    out["noise_multiplier_changed"] = [d.feeder_ids[f] for f in range(len(d.feeder_ids))
                                       if not np.allclose(d.noise_mult[f, sl], tw.noise_mult[f, sl])]
    out["unmetered_energy_kwh"] = {d.dt_ids[k]: float(d.unmetered_kw[k, sl].sum())
                                   for k in range(len(d.dt_ids)) if d.unmetered_kw[k, sl].sum() > 0}
    out["note"] = ("Both runs share the seed, so every background random stream is identical; differences are "
                   "caused only by the injected scenario.")
    return _clean(out)


@app.post("/api/simulations/{sim_id}/replay", tags=["simulation"])
def replay(sim_id: str, t: int = Query(..., ge=0)):
    """Regenerate the run from its stored configuration and seed and compare data and detector outputs."""
    run = S.get(sim_id)
    t0 = time.perf_counter()
    ctx = prepare(run.config, run.rules)
    ft = ctx.features.at(run.tau(t))
    tables = ctx.features.tables(ft, run_id=run.id)
    scores = S.bundle.score_consumers(tables["consumer"])
    orig = run.evaluate(t)["consumer_scores"]
    diff = float(np.max(np.abs(scores.to_numpy() - orig.to_numpy())))
    return {"original_hash": run.d.data_hash, "replay_hash": ctx.data.data_hash,
            "data_identical": run.d.data_hash == ctx.data.data_hash, "max_abs_score_difference": diff,
            "scores_identical_within_1e-12": diff <= 1e-12, "replay_ms": round((time.perf_counter() - t0) * 1000, 1)}


@app.get("/api/detections", tags=["detection"])
def detections(sim_id: str | None = None, limit: int = Query(100, ge=1, le=1000)):
    return S.store.list_detections(sim_id, limit)


# --------------------------------------------------------------------------- experiments
@app.get("/api/experiments/results", tags=["experiments"])
def experiment_results():
    """Results written by `python -m gridwatch.experiments.run` (never hard-coded)."""
    path = RESULTS_DIR / "results.json"
    if not path.exists():
        return {"available": False, "message": "No experiment results yet. Run: python -m gridwatch.experiments.run"}
    return {"available": True, **json.loads(path.read_text())}


# ------------------------------------------------------------------------------ frontend
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, f"unknown API path /{path}")
        f = FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
