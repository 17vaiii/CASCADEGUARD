# OWNER: P4 | STATUS: ACTIVE
"""Regression tests for gaps found in the 2026-11-07 PRD audit: intervals, feeder meters, hashed IDs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cascadeguard.theft import hashed_id


def test_hashed_id_is_stable_and_hides_the_id():
    a = hashed_id("C0000001")
    assert a == hashed_id("C0000001") and a != hashed_id("C0000002")
    assert a.startswith("H-") and "0000001" not in a


def _bundle(cfg, ds, features):
    from cascadeguard.theft.pipeline import fit_consumer_models
    from cascadeguard.theft.anomaly import UnsupervisedDetectors  # noqa: F401
    c = ds.consumers
    y = c.is_theft.to_numpy().astype(int)
    ctype = c.set_index("consumer_id").consumer_type.reindex(features.index)
    split = c.split.to_numpy()
    res = fit_consumer_models(features, ctype, y, split == "train", split == "validation", cfg, 7)
    return {"config": cfg, "unsupervised": res["unsupervised"], "supervised": res["supervised"],
            "fusion": res["fusion"], "version": "test"}, res


def test_probability_intervals_are_valid(cfg, ds, features):
    _, res = _bundle(cfg, ds, features)
    iv = res["fusion"].probability_interval(np.array([0.01, 0.2, 0.5, 0.9]))
    assert iv.shape == (4, 2)
    assert ((iv >= 0) & (iv <= 1)).all() and (iv[:, 0] <= iv[:, 1] + 1e-9).all()
    assert iv[3, 1] >= iv[0, 0]


def test_feeder_meters_give_network_context(cfg, ds, features):
    from cascadeguard.theft.service import score_frame, network_summary
    bundle, _ = _bundle(cfg, ds, features)
    fid = ds.feeders.feeder_id.iloc[0]
    ids = ds.consumers.consumer_id[ds.consumers.feeder_id == fid].tolist()
    frame = ds.to_meter_frame(ids)[["timestamp", "consumer_id", "feeder_id", "consumer_type", "metered_kwh"]]
    inputs = pd.DataFrame({"timestamp": ds.timestamps, "feeder_id": fid, "input_kwh": ds.feeder_input_kwh[0]})
    summary = network_summary(inputs, frame, "feeder_id", "feeder_id", ds.timestamps, ds.history_end)
    assert list(summary.node_id) == [fid] and np.isfinite(summary.z.iloc[0])
    out = score_frame(frame, str(ds.timestamps[ds.history_end]), bundle, feeder_summary=summary, top_k=3)
    assert not out["warnings"]
    lead = out["leads"][0]
    assert lead["consumer_ref"].startswith("H-")
    low, high = lead["score_interval"]
    assert 0 <= low <= high <= 1
