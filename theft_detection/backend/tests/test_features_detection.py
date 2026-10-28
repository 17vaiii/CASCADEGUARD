"""Feature causality, labels, model scoring and explanations."""

import numpy as np
import pytest

from gridwatch.detection.methods import CONSUMER_METHODS, UNIT_METHODS
from gridwatch.explanations.explain import rf_contributions
from gridwatch.features.build import COMBINED_FEATURES, CONSUMER_FEATURES
from gridwatch.pipeline import prepare
from gridwatch.simulation.scenarios import Injection, SimulationConfig


def test_features_are_causal(normal_ctx):
    """Changing data after tau must not change features at tau."""
    ctx = prepare(SimulationConfig(scenario="A", seed=11))
    tau = ctx.data.h0 + 100
    before = ctx.features.at(tau)["consumer_X"].copy()
    ctx.data.meter_kwh[:, tau + 1:] *= 3.0
    ctx.data.dt_meter_kwh[:, tau + 1:] *= 3.0
    ctx.data.feeder_meter_kwh[:, tau + 1:] *= 3.0
    after = ctx.features.at(tau)["consumer_X"]
    assert np.allclose(before, after)


def test_window_labels_follow_injection():
    ctx = prepare(SimulationConfig(scenario="B", seed=21, injections=[
        Injection(type="sudden_deviation", feeder="F2", n_consumers=2, magnitude=60, onset_day=5, duration_days=4)]))
    ev = ctx.data.events[0]
    i = int(np.flatnonzero(ctx.data.consumer_ids == ev.consumers[0])[0])
    lab_before = ctx.features.labels_at(ev.start_hour - 1)["consumer"][i]
    lab_partial = ctx.features.labels_at(ev.start_hour + 5)["consumer"][i]
    lab_during = ctx.features.labels_at(ev.start_hour + 30)["consumer"][i]
    assert (lab_before, lab_partial, lab_during) == (0, -1, 1)


def test_scores_have_expected_ranges(small_bundle):
    ctx = prepare(SimulationConfig(scenario="A", seed=33))
    tables = ctx.features.tables(ctx.features.at(ctx.data.h0 + 150))
    cs = small_bundle.score_consumers(tables["consumer"])
    assert set(cs.columns) == set(CONSUMER_METHODS)
    for m in ("rf_consumer", "rf_combined"):
        assert cs[m].between(0, 1).all()
    for kind in ("dt", "feeder"):
        us = small_bundle.score_units(kind, tables[kind], tables["consumer"], cs)
        assert set(us.columns) == set(UNIT_METHODS) and len(us) == len(tables[kind])
        assert us.notna().all().all()


def test_rf_contributions_are_exact(small_bundle):
    ctx = prepare(SimulationConfig(scenario="A", seed=34))
    X = ctx.features.at(ctx.data.h0 + 120)["consumer_X"]
    rf = small_bundle.rf_combined
    for row in X[:5]:
        base, contrib = rf_contributions(rf, row)
        assert base + contrib.sum() == pytest.approx(rf.predict_proba(row[None, :])[0, 1], abs=1e-9)
    xs = X[0][[COMBINED_FEATURES.index(f) for f in CONSUMER_FEATURES]]
    base, contrib = rf_contributions(small_bundle.rf_consumer, xs)
    assert base + contrib.sum() == pytest.approx(small_bundle.rf_consumer.predict_proba(xs[None, :])[0, 1], abs=1e-9)


def test_unmetered_load_is_flagged_at_dt_level(small_bundle, unmetered_ctx):
    """An obvious unmetered load (60 % of DT load) must be caught by the DT energy-balance rule."""
    tau = unmetered_ctx.data.h0 + 6 * 24
    ft = unmetered_ctx.features.at(tau)
    k = unmetered_ctx.data.dt_ids.index("F3-DT2")
    assert ft["units"]["dt"]["balance_rule"][k] >= 1.0
    others = np.delete(ft["units"]["dt"]["balance_rule"], k)
    assert (others < 1.0).all()
