# OWNER: P4 | STATUS: ACTIVE
"""T9 theft-aware grid state, T8 HT tapping, public dataset loader and the scoring service."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cascadeguard.theft import hidden_load as hl


@pytest.fixture(scope="module")
def ratio():
    return pd.DataFrame({"substation": ["SHIMOGA", "SIRA_KBCROSS", "NELAMANGALA", "PEENYA"],
                         "est_ntl_ratio": [0.02, 0.01, 0.03, 0.04],
                         "true_ntl_ratio": [0.025, 0.01, 0.03, 0.045]})


def test_hidden_load_vector_contract(ratio):
    metered = hl.metered_substation_mw("monsoon")
    vec = hl.hidden_load_vector(ratio, metered, 2.0)
    assert {v["bus_id"] for v in vec} == set(metered)
    for v in vec:
        assert v["hidden_load_mw"] >= 0 and v["source"] == "suspected_unmetered_load"
    peenya = next(v for v in vec if v["bus_id"] == "PEENYA")
    assert peenya["hidden_load_mw"] == pytest.approx(metered["PEENYA"] * 0.04 * 2.0, rel=1e-3)


def test_hidden_load_raises_line_loading(ratio):
    base = hl.corridor_state("summer")
    vec = hl.hidden_load_vector(ratio, hl.metered_substation_mw("summer"), 3.0)
    aware = hl.corridor_state("summer", vec)
    assert aware.res_line.loading_percent.max() > base.res_line.loading_percent.max()
    assert aware["total_load_mw"] == pytest.approx(aware.load.p_mw.sum())
    snap = hl.snapshot_from_net(aware, [3])
    assert len(snap["line_from_bus"]) == len(aware.line) and snap["initial_trips"] == [3]


def test_theft_aware_state_predicts_truth_better(ratio, cfg):
    c = dict(cfg)
    c["hidden_load"] = {**cfg["hidden_load"], "seasons": ["monsoon"], "intensity": [5.0], "n2_sample": 4}
    res = hl.theft_aware_experiment(ratio, c, n_jobs=1, use_gnn=False)
    s = res["summary"][0]
    assert s["aware_sim_mae_mw"] <= s["scada_sim_mae_mw"]
    assert s["aware_sim_missed_cascades"] <= s["scada_sim_missed_cascades"]


def test_ht_tap_detection_large_tap(cfg):
    from cascadeguard.theft.ht_tapping import TapDetector
    det = TapDetector("post_monsoon", cfg)
    det.calibrate(n=40, seed=1)
    rng = np.random.default_rng(3)
    res = det.analyse(det.simulate_case(rng, "TAP_150", 30.0))
    assert res["suspicious"]
    assert abs(res["est_km"] - 150) <= 60
    assert 10 < res["est_mw"] < 50


def test_public_dataset_loader(tmp_path):
    from cascadeguard.theft.public_datasets import daily_features, load_sgcc
    dates = pd.date_range("2015-01-01", periods=40).strftime("%Y/%m/%d")
    rows = np.random.default_rng(0).gamma(2, 5, (6, 40))
    rows[0, 20:] = 0.0
    df = pd.DataFrame(rows, columns=dates)
    df.insert(0, "FLAG", [1, 0, 0, 0, 0, 0])
    df.insert(0, "CONS_NO", [f"X{i}" for i in range(6)])
    df.to_csv(tmp_path / "sgcc.csv", index=False)
    reads, d, meta = load_sgcc(tmp_path / "sgcc.csv")
    assert reads.shape == (6, 40) and meta.label.sum() == 1 and d.is_monotonic_increasing
    f = daily_features(reads)
    assert f.f_zero_frac_recent.iloc[0] == 1.0


def test_service_end_to_end(ds, cfg, tmp_path):
    """Train a tiny bundle with the pipeline, then score P2-contract meter rows through the service."""
    from cascadeguard.theft.pipeline import run_pipeline
    from cascadeguard.theft.service import load_bundle, score_consumers
    run_pipeline(tmp_path / "out", tmp_path / "models", scale=0.3, seed=7, run_t9=False, run_t8=False,
                 n_jobs=1, config=cfg)
    bundle_path = str(tmp_path / "models" / "theft_bundle.joblib")
    ids = ds.consumers.consumer_id.head(12).tolist()
    frame = ds.to_meter_frame(ids)
    payload = {"readings": frame[["timestamp", "consumer_id", "feeder_id", "consumer_type", "metered_kwh"]]
               .assign(timestamp=frame.timestamp.astype(str)).to_dict(orient="records"),
               "history_end": str(ds.timestamps[ds.history_end]), "top_k": 5}
    out = score_consumers(payload, bundle_path)
    assert len(out["leads"]) == 5 and out["requires_human_inspection"] is True
    assert out["warnings"]                        # no feeder meters supplied -> warned
    assert all(0 <= lead["score"] <= 1 and lead["reason_codes"] is not None for lead in out["leads"])
    load_bundle.cache_clear()
