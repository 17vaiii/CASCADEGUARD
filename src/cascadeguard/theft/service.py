# OWNER: P4 | NEEDS: P2 | STATUS: ACTIVE
"""Inference service for ``POST /api/theft-score`` and the P5 dashboard.

The trained bundle (``data/models/theft/theft_bundle.joblib``, written by
``python -m cascadeguard.theft.pipeline``) holds the unsupervised detectors, the supervised
model, the fusion/calibration model and the theft case base. :func:`score_consumers` accepts
interval reads in the P2 meter-contract shape and returns ranked inspection leads with a
calibrated score, conformal confidence, reason codes and similar past cases.

Optional ``feeder_inputs`` / ``dt_inputs`` (input-meter rows) give the energy-balance context.
Readings must then cover every consumer below those nodes. Without them the network-context
features are unavailable; the response carries a warning and relies on consumer evidence only.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from cascadeguard.theft import DISCLAIMER, REPO_ROOT, hashed_id
from cascadeguard.theft.energy_balance import _summarise
from cascadeguard.theft.features import consumer_features, context_features
from cascadeguard.theft.reason_codes import consumer_reason_codes, summary_sentence
from cascadeguard.theft.supervised import model_matrix
from cascadeguard.theft.tamper_signals import tamper_features, tamper_summary

BUNDLE_PATH = REPO_ROOT / "data" / "models" / "theft" / "theft_bundle.joblib"


class BundleMissing(RuntimeError):
    pass


@lru_cache(maxsize=2)
def load_bundle(path: str | None = None) -> dict[str, Any]:
    p = Path(path or BUNDLE_PATH)
    if not p.exists():
        raise BundleMissing(f"theft model bundle not found at {p}; run `python -m cascadeguard.theft.pipeline`")
    return joblib.load(p)


def network_summary(inputs: pd.DataFrame, frame: pd.DataFrame, key: str, node_col: str, ts: pd.DatetimeIndex,
                    history_idx: int, flag_z: float = 3.0) -> pd.DataFrame:
    """Residual-change summary per node from input-meter rows ``timestamp, <node_col>, input_kwh``.

    Technical loss is not subtracted here: the score uses the *change* of the residual against
    the node's own reference period, and a roughly constant technical share cancels out.
    """
    rows = inputs.copy()
    rows["timestamp"] = pd.to_datetime(rows.timestamp, utc=True)
    metered = frame.groupby([key, "timestamp"]).metered_kwh.sum().rename("metered_kwh").reset_index()
    merged = rows.merge(metered, left_on=[node_col, "timestamp"], right_on=[key, "timestamp"], how="inner")
    if merged.empty:
        raise ValueError(f"{node_col} rows do not overlap the readings")
    step_h = (ts[1] - ts[0]).total_seconds() / 3600.0
    per_day = int(round(24 / step_h))
    merged["day"] = ((merged.timestamp - ts[0]).dt.total_seconds() / 86400.0).astype(int)
    merged["residual_kwh"] = merged.input_kwh - merged.metered_kwh
    daily = merged.groupby([node_col, "day"], as_index=False).agg(input_kwh=("input_kwh", "sum"),
                                                                  residual_kwh=("residual_kwh", "sum"))
    daily = daily.rename(columns={node_col: "node_id"})
    daily["residual_pct"] = 100.0 * daily.residual_kwh / daily.input_kwh.clip(lower=1e-9)
    return _summarise(daily, history_idx // per_day, flag_z)


def score_frame(frame: pd.DataFrame, history_end: str | pd.Timestamp, bundle: dict[str, Any],
                tamper_log: pd.DataFrame | None = None, feeder_summary: pd.DataFrame | None = None,
                dt_summary: pd.DataFrame | None = None, top_k: int = 20, n_similar: int = 5) -> dict[str, Any]:
    """Score consumers from a long meter frame (``timestamp, consumer_id, feeder_id, consumer_type,
    metered_kwh`` [+ ``dt_id``]). ``history_end`` separates the reference period from the
    scoring window."""
    warnings: list[str] = []
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    wide = frame.pivot_table(index="consumer_id", columns="timestamp", values="metered_kwh", aggfunc="sum")
    ts = pd.DatetimeIndex(wide.columns)
    if len(ts) < 48:
        raise ValueError("need at least 48 intervals of reads per consumer")
    h_end = pd.Timestamp(history_end)
    h_end = h_end.tz_localize("UTC") if h_end.tzinfo is None else h_end.tz_convert("UTC")
    history_idx = int(np.searchsorted(ts.values, h_end.to_datetime64()))
    if history_idx < 24 or history_idx > len(ts) - 24:
        raise ValueError("history_end must leave at least one day on each side")
    meta = frame.drop_duplicates("consumer_id").set_index("consumer_id").reindex(wide.index).reset_index()
    if "dt_id" not in meta:
        meta["dt_id"] = meta.feeder_id
    feats = consumer_features(wide.to_numpy(dtype=float), ts, history_idx, meta, bundle["config"])
    log = None
    if tamper_log is not None and len(tamper_log):
        log = tamper_log.copy()
        log["t_idx"] = np.searchsorted(ts.values, pd.to_datetime(log.timestamp, utc=True).values)
    feats = feats.join(tamper_features(log, meta.consumer_id, history_idx, len(ts)))
    if feeder_summary is None:
        warnings.append("No feeder/DT input meters supplied: network energy-balance context unavailable.")
        feeder_summary = pd.DataFrame({"node_id": meta.feeder_id.unique(), "z": np.nan, "peak_change_pct": np.nan})
    feats = feats.join(context_features(meta, feeder_summary, dt_summary))

    scores = bundle["unsupervised"].score(feats)
    x = model_matrix(feats, meta.set_index("consumer_id").consumer_type.reindex(feats.index))
    scores["s_gbm"] = bundle["supervised"].predict_proba(x)
    stack = feats.join(scores)
    prob = bundle["fusion"].predict_proba(stack)
    sets = bundle["fusion"].prediction_sets(prob)
    order = np.argsort(-prob, kind="stable")[:top_k]
    intervals = bundle["fusion"].probability_interval(prob[order]) if len(order) else np.zeros((0, 2))
    similar = bundle["case_base"].query(feats.iloc[order], n_similar) if "case_base" in bundle else [[] for _ in order]
    leads = []
    for rank, (i, sim, iv) in enumerate(zip(order, similar, intervals), start=1):
        cid = feats.index[i]
        m = meta.iloc[i]
        codes = consumer_reason_codes(feats.iloc[i], tamper_summary(log, cid, history_idx) if log is not None else None,
                                      m.feeder_id, m.dt_id)
        conf = str(sets.confidence.iloc[i])
        leads.append({
            "rank": rank, "consumer_id": str(cid), "consumer_ref": hashed_id(str(cid)), "feeder_id": str(m.feeder_id),
            "consumer_type": str(m.consumer_type), "score": round(float(prob[i]), 4),
            "score_interval": [round(float(iv[0]), 4), round(float(iv[1]), 4)], "confidence": conf,
            "reason_codes": codes, "summary": summary_sentence(codes, float(prob[i]), conf),
            "similar_cases": sim,
        })
    return {"leads": leads, "n_scored": int(len(feats)), "model_version": bundle.get("version", "theft_v1"),
            "warnings": warnings, "requires_human_inspection": True, "disclaimer": DISCLAIMER}


def score_consumers(payload: dict[str, Any], bundle_path: str | None = None) -> dict[str, Any]:
    """API entry point. ``payload``::

        {"readings": [{"timestamp", "consumer_id", "feeder_id", "consumer_type", "metered_kwh"}, ...],
         "history_end": "2025-04-15T00:00:00Z",
         "tamper_events": [{"consumer_id", "timestamp", "event_type"}, ...],   # optional
         "feeder_inputs": [{"timestamp", "feeder_id", "input_kwh"}, ...],      # optional
         "dt_inputs": [{"timestamp", "dt_id", "input_kwh"}, ...],              # optional (readings need dt_id)
         "top_k": 20}
    """
    bundle = load_bundle(bundle_path)
    readings = pd.DataFrame(payload.get("readings") or [])
    required = {"timestamp", "consumer_id", "feeder_id", "consumer_type", "metered_kwh"}
    if readings.empty or not required.issubset(readings.columns):
        raise ValueError(f"readings must contain {sorted(required)}")
    tamper = pd.DataFrame(payload.get("tamper_events") or [])
    feeder_summary, dt_summary = None, None
    if payload.get("feeder_inputs") or payload.get("dt_inputs"):
        frame = readings.assign(timestamp=pd.to_datetime(readings.timestamp, utc=True))
        ts = pd.DatetimeIndex(sorted(frame.timestamp.unique()))
        h_end = pd.Timestamp(payload["history_end"])
        h_end = h_end.tz_localize("UTC") if h_end.tzinfo is None else h_end.tz_convert("UTC")
        history_idx = int(np.searchsorted(ts.values, h_end.to_datetime64()))
        if payload.get("feeder_inputs"):
            feeder_summary = network_summary(pd.DataFrame(payload["feeder_inputs"]), frame, "feeder_id", "feeder_id", ts, history_idx)
        if payload.get("dt_inputs"):
            if "dt_id" not in frame:
                raise ValueError("dt_inputs need dt_id on every reading")
            dt_summary = network_summary(pd.DataFrame(payload["dt_inputs"]), frame, "dt_id", "dt_id", ts, history_idx)
    return score_frame(readings, payload["history_end"], bundle, tamper if len(tamper) else None,
                       feeder_summary, dt_summary, top_k=int(payload.get("top_k", 20)))
