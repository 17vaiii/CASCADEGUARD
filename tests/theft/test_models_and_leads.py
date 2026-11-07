# OWNER: P4 | STATUS: ACTIVE
"""T3-T7 models, fusion/calibration, P4-6 graph, T5 reason codes, T6 inspection, P4-11, T10."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cascadeguard.theft.anomaly import UnsupervisedDetectors, threshold_baseline_score
from cascadeguard.theft.case_retrieval import TheftCaseBase, outcome_labels
from cascadeguard.theft.fairness import fairness_report
from cascadeguard.theft.features import BEHAVIOUR_COLUMNS, consumer_features
from cascadeguard.theft.graph_theft import build_theft_graph, train_graph_model
from cascadeguard.theft.inspection import build_lead_table, compare_strategies
from cascadeguard.theft.metrics import expected_calibration_error, precision_at_k, ranking_metrics
from cascadeguard.theft.pipeline import fit_consumer_models
from cascadeguard.theft.reason_codes import consumer_reason_codes, summary_sentence
from cascadeguard.theft.tamper_signals import tamper_features


@pytest.fixture(scope="module")
def fitted(ds, features, cfg):
    c = ds.consumers
    y = c.is_theft.to_numpy().astype(int)
    ctype = c.set_index("consumer_id").consumer_type.reindex(features.index)
    split = c.split.to_numpy()
    return y, split, fit_consumer_models(features, ctype, y, split == "train", split == "validation", cfg, 7)


def test_features_do_not_read_labels(ds, cfg):
    c = ds.consumers
    meta = c[["consumer_id", "feeder_id", "consumer_type"]]
    f1 = consumer_features(ds.metered_kwh, ds.timestamps, ds.history_end, meta, cfg)
    shuffled = c.assign(theft_type=np.random.default_rng(0).permutation(c.theft_type.to_numpy()))
    f2 = consumer_features(ds.metered_kwh, ds.timestamps, ds.history_end,
                           shuffled[["consumer_id", "feeder_id", "consumer_type"]], cfg)
    pd.testing.assert_frame_equal(f1, f2)
    assert set(BEHAVIOUR_COLUMNS) <= set(f1.columns)


def test_signatures_point_the_right_way(ds, features):
    c = ds.consumers.set_index("consumer_id")
    f = features
    stop = c.index[c.theft_type == "meter_stop"]
    normal = c.index[(c.theft_type == "none") & (c.lookalike_type == "none") & ~c.comm_gap]
    assert f.loc[stop, "f_zero_frac_recent"].mean() > 5 * f.loc[normal, "f_zero_frac_recent"].mean() + 0.05
    solar = c.index[c.lookalike_type == "rooftop_solar"]
    assert f.loc[solar, "f_solar_signature"].median() > f.loc[normal, "f_solar_signature"].median()
    gap = c.index[c.comm_gap]
    if len(gap):
        assert f.loc[gap, "f_missing_frac"].min() > 0


def test_tamper_features_counts(ds):
    tf = tamper_features(ds.tamper_log, ds.consumers.consumer_id, ds.history_end, ds.n_periods)
    recent = ds.tamper_log[ds.tamper_log.t_idx >= ds.history_end]
    assert tf.f_tamper_total_recent.sum() == len(recent)


def test_models_beat_random_and_are_calibrated(fitted):
    y, split, res = fitted
    test = split == "test"
    prob = res["prob"]
    assert ((prob >= 0) & (prob <= 1)).all()
    m = ranking_metrics(y[test], prob[test], 10)
    assert m["auroc"] > 0.7
    assert m["pr_auc"] > 2 * y[test].mean()
    assert expected_calibration_error(prob[test], y[test]) < 0.15
    cov = res["fusion"].coverage(prob[test], y[test])
    assert cov > 0.75
    assert set(res["fusion"].prediction_sets(prob).confidence) <= {"high", "medium", "low"}


def test_metrics_helpers():
    y = np.array([1, 0, 1, 0, 0])
    s = np.array([0.9, 0.8, 0.7, 0.1, 0.0])
    assert precision_at_k(y, s, 2) == 0.5
    assert expected_calibration_error(np.array([1.0, 0.0]), np.array([1, 0])) == 0.0


def test_graph_model_runs(ds, features, balances, fitted, cfg):
    y, split, res = fitted
    fb, db = balances
    gx = features[[c for c in features.columns if c.startswith("f_") and not c.startswith(("f_feeder", "f_dt"))]]
    data, info = build_theft_graph(ds.consumers, gx, db.summary, fb.summary, ds.dts, ds.feeders)
    assert data.num_nodes == len(ds.consumers) + len(ds.dts) + len(ds.feeders)
    prob, meta = train_graph_model(data, info["n_consumers"], y, split, cfg, 7)
    assert prob.shape == (len(ds.consumers),) and np.isfinite(prob).all()


def test_reason_codes_wording(ds, features):
    c = ds.consumers.set_index("consumer_id")
    cid = c.index[c.theft_type == "meter_stop"][0]
    codes = consumer_reason_codes(features.loc[cid], {"cover_open": 2}, c.at[cid, "feeder_id"], c.at[cid, "dt_id"])
    assert codes and all({"code", "text", "weight", "kind"} <= set(x) for x in codes)
    text = summary_sentence(codes, 0.8, "high").lower()
    assert "suspected" in text and "verification" in text
    for bad in ("confirmed", "thief", "guilty", "proven"):
        assert bad not in text
    solar = c.index[c.lookalike_type == "rooftop_solar"]
    kinds = [x["code"] for s in solar for x in consumer_reason_codes(features.loc[s])]
    assert "SOLAR_LIKE" in kinds


def test_inspection_value_beats_random(ds, features, balances, fitted, cfg):
    y, split, res = fitted
    _, db = balances
    c = ds.consumers
    ntl = pd.Series(ds.ntl_kwh[:, ds.history_end:].sum(axis=1), index=c.consumer_id.to_numpy())
    dt_true = pd.Series(0.0, index=ds.dts.dt_id)
    leads = build_lead_table(c, features, res["prob"], threshold_baseline_score(features),
                             ds.n_periods - ds.history_end, db.summary, ds.dts,
                             pd.Series(0.1, index=db.summary.node_id), ntl, dt_true)
    depots = {s: (float(x), 0.0) for s, x in ds.feeders.groupby("substation").x_km.first().items()}
    table = compare_strategies(leads, 15, depots, cfg, 7, random_repeats=5).set_index("strategy")
    assert table.loc["expected_value", "recovered_kwh"] > table.loc["random", "recovered_kwh"]
    assert table.loc["score", "precision"] > table.loc["random", "precision"]
    assert table.loc["value_route", "visits"] <= 15


def test_fairness_report_structure(ds, fitted):
    y, split, res = fitted
    scored = ds.consumers[["area", "consumer_type", "is_theft"]].assign(prob=res["prob"])
    rep = fairness_report(scored, 15)
    top = rep["operating_points"]["top_k"]
    assert {"area", "consumer_type"} <= set(top["fpr_disparity_ratio"])
    assert all(0 <= g["flag_rate"] <= 1 for g in top["by_group"])


def test_case_retrieval_excludes_self(ds, features):
    out = outcome_labels(ds.consumers)
    base = TheftCaseBase().fit(features, out)
    q = features.iloc[:3]
    res = base.query(q, 4)
    assert all(len(r) == 4 for r in res)
    assert all(m["case_id"] != cid for r, cid in zip(res, q.index) for m in r)
    assert base.padded_vectors().shape[1] == 128
