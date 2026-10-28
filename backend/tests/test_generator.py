"""Synthetic data generator: reproducibility, scenario isolation, validation."""

import numpy as np
import pytest
from pydantic import ValidationError

from gridwatch.simulation.generator import generate
from gridwatch.simulation.scenarios import Injection, SimulationConfig


def test_same_seed_same_data():
    a = generate(SimulationConfig(seed=123))
    b = generate(SimulationConfig(seed=123))
    assert a.data_hash == b.data_hash
    assert np.array_equal(np.nan_to_num(a.meter_kwh, nan=-1), np.nan_to_num(b.meter_kwh, nan=-1))


def test_different_seed_different_data():
    assert generate(SimulationConfig(seed=1)).data_hash != generate(SimulationConfig(seed=2)).data_hash


def test_sudden_deviation_changes_only_target_meters():
    base = generate(SimulationConfig(seed=8))
    scen = generate(SimulationConfig(scenario="B", seed=8, injections=[
        Injection(type="sudden_deviation", feeder="F2", n_consumers=3, magnitude=50, onset_day=4, duration_days=5)]))
    targets = set(scen.events[0].consumers)
    assert len(targets) == 3 and all(c.startswith("C-F2-") for c in targets)
    diff = np.nansum(np.abs(np.nan_to_num(scen.meter_kwh) - np.nan_to_num(base.meter_kwh)), axis=1) > 1e-9
    assert set(scen.consumer_ids[diff]) == targets
    # The energy actually drawn is unchanged, so DT and feeder meters are identical to normal operation.
    assert np.array_equal(np.nan_to_num(scen.dt_meter_kwh), np.nan_to_num(base.dt_meter_kwh))
    assert np.array_equal(np.nan_to_num(scen.feeder_meter_kwh), np.nan_to_num(base.feeder_meter_kwh))
    i = int(np.flatnonzero(scen.consumer_ids == sorted(targets)[0])[0])
    s, e = scen.events[0].start_hour, scen.events[0].end_hour
    assert scen.recorded_kwh[i, s:e] == pytest.approx(0.5 * scen.true_kwh[i, s:e])
    assert scen.label_theft_consumer[i, s:e].all() and not scen.label_theft_consumer[i, :s].any()


def test_unmetered_load_flows_through_dt_and_feeder_meters_only():
    base = generate(SimulationConfig(seed=8))
    scen = generate(SimulationConfig(scenario="C", seed=8, injections=[
        Injection(type="unmetered_load", feeder="F1", dt="F1-DT2", magnitude=40, onset_day=2, duration_days=4)]))
    k = scen.dt_ids.index("F1-DT2")
    assert scen.unmetered_kw[k].sum() > 0
    assert np.array_equal(np.nan_to_num(scen.meter_kwh), np.nan_to_num(base.meter_kwh))
    assert scen.dt_true_kwh[k].sum() > base.dt_true_kwh[k].sum()
    same_feeder = [j for j, d in enumerate(scen.dt_ids) if d.startswith("F1-") and j != k]
    other_feeders = [j for j, d in enumerate(scen.dt_ids) if not d.startswith("F1-")]
    assert np.array_equal(scen.dt_true_kwh[other_feeders], base.dt_true_kwh[other_feeders])
    # Same-feeder DTs see only the small voltage-coupling effect on their LV losses.
    rel = np.abs(scen.dt_true_kwh[same_feeder].sum(axis=1) / base.dt_true_kwh[same_feeder].sum(axis=1) - 1)
    assert (rel < 1e-3).all()
    f2 = scen.feeder_ids.index("F2")
    assert np.allclose(scen.feeder_true_kwh[f2], base.feeder_true_kwh[f2])


def test_benign_and_injected_labels_are_distinct():
    d = generate(SimulationConfig(seed=17, benign_change_rate=0.1))
    assert d.label_benign_change.any()
    assert not d.label_theft_consumer.any()


@pytest.mark.parametrize("bad", [
    dict(scenario="B", injections=[]),
    dict(scenario="A", injections=[Injection(type="noise_stress", feeder="F1", magnitude=3)]),
    dict(scenario="C", n_feeders=2, injections=[Injection(type="unmetered_load", feeder="F4", magnitude=20)]),
    dict(seed=-1),
    dict(noise_level=50),
])
def test_invalid_configs_are_rejected(bad):
    with pytest.raises(ValidationError):
        SimulationConfig(**bad)


def test_injection_magnitude_limits():
    with pytest.raises(ValidationError):
        Injection(type="sudden_deviation", feeder="F1", magnitude=99)
    with pytest.raises(ValidationError):
        Injection(type="unmetered_load", feeder="F1", dt="F2-DT1", magnitude=20)
