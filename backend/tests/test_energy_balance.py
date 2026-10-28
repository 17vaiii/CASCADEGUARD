"""Energy-accounting tests: identities, known injected energy, data-quality handling."""

import numpy as np
import pytest

from gridwatch.pipeline import prepare
from gridwatch.simulation.generator import _ingest
from gridwatch.simulation.scenarios import Injection, SimulationConfig


def test_balance_identity_holds(normal_ctx):
    d, acc = normal_ctx.data, normal_ctx.accountant
    a = d.h0 + 48
    for kind, uid in (("feeder", "F1"), ("dt", "F2-DT3")):
        b = acc.balance(kind, uid, a, a + 72, a + 71)
        lhs = b["input_kwh"] - b["metered_kwh"] - b["imputed_kwh"] - b["estimated_loss_kwh"]
        assert b["unexplained_kwh"] == pytest.approx(lhs, abs=1e-9)
        hourly = np.array([x for x in b["hourly"]["unexplained"] if x is not None])
        assert hourly.sum() == pytest.approx(b["unexplained_kwh"], abs=0.01 * len(hourly))


def test_normal_operation_is_within_uncertainty(normal_ctx):
    d, acc = normal_ctx.data, normal_ctx.accountant
    zs = []
    for day in range(14):
        a = d.h0 + 24 * day
        comp = acc.components(a, a + 24, a + 23)
        for kind in ("feeder", "dt"):
            zs.extend(acc.window_stats(comp, kind, a, a + 24)["z"])
    zs = np.array(zs)
    assert np.abs(zs.mean()) < 0.5
    assert (np.abs(zs) > 3).mean() < 0.01


def test_injected_unmetered_energy_is_recovered(normal_ctx, unmetered_ctx):
    """Known case: the DT balance must recover the injected energy plus the extra LV losses it causes."""
    d = unmetered_ctx.data
    k = d.dt_ids.index("F3-DT2")
    a, b = d.h0 + 72, d.h0 + 72 + 8 * 24
    injected = d.unmetered_kw[k, a:b].sum()
    assert injected > 0
    u_s = unmetered_ctx.accountant.balance("dt", "F3-DT2", a, b, b - 1)["unexplained_kwh"]
    u_n = normal_ctx.accountant.balance("dt", "F3-DT2", a, b, b - 1)["unexplained_kwh"]
    extra_lv_loss = d.true_loss_kwh["lv_dt"][k, a:b].sum() - normal_ctx.data.true_loss_kwh["lv_dt"][k, a:b].sum()
    recovered = u_s - u_n
    assert recovered == pytest.approx(injected + extra_lv_loss, rel=0.03)
    # A neighbouring DT changes only by electrical coupling: the extra current on the shared 11 kV
    # segment lowers its voltage slightly, so its (constant-power) LV losses rise a little.
    j = d.dt_ids.index("F3-DT1")
    shift = (unmetered_ctx.accountant.balance("dt", d.dt_ids[j], a, b, b - 1)["unexplained_kwh"]
             - normal_ctx.accountant.balance("dt", d.dt_ids[j], a, b, b - 1)["unexplained_kwh"])
    assert 0 <= shift < 0.01 * injected


def test_feeder_head_energy_equals_demand_plus_true_losses(normal_ctx):
    d = normal_ctx.data
    for f in range(len(d.feeder_ids)):
        dts = d.dt_feeder_idx() == f
        demand = d.true_kwh[d.consumer_feeder_idx == f].sum() + d.unmetered_kw[dts].sum()
        losses = sum(d.true_loss_kwh[k][f].sum() for k in ("mv", "dt_cu", "dt_core", "lv"))
        assert d.feeder_true_kwh[f].sum() == pytest.approx(demand + losses, rel=1e-9)


def test_missing_readings_are_imputed_not_counted_as_loss():
    base = prepare(SimulationConfig(scenario="A", seed=5))
    faulty = prepare(SimulationConfig(scenario="E", seed=5, injections=[
        Injection(type="missing_delayed", feeder="F2", n_consumers=10, magnitude=80, onset_day=2, duration_days=6)]))
    a, b = faulty.data.h0 + 2 * 24, faulty.data.h0 + 8 * 24
    bf = faulty.accountant.balance("feeder", "F2", a, b, b - 1)
    bn = base.accountant.balance("feeder", "F2", a, b, b - 1)
    assert bf["imputed_kwh"] > 3 * bn["imputed_kwh"]
    assert bf["data_quality"]["consumer_reading_coverage"] < bn["data_quality"]["consumer_reading_coverage"]
    # Imputation keeps the unexplained energy close to normal operation (within the propagated uncertainty).
    assert abs(bf["unexplained_kwh"] - bn["unexplained_kwh"]) < 2 * bf["sigma_kwh"]
    assert bf["sigma_kwh"] > bn["sigma_kwh"]


def test_delayed_readings_become_available_after_arrival():
    ctx = prepare(SimulationConfig(scenario="E", seed=9, injections=[
        Injection(type="missing_delayed", feeder="F1", n_consumers=5, magnitude=60, onset_day=2, duration_days=3)]))
    d, acc = ctx.data, ctx.accountant
    delayed = np.argwhere(np.isfinite(d.arrival_delay) & (d.arrival_delay >= 12))
    i, h = delayed[0]
    early = acc.components(h, h + 1, int(h))  # evaluated at the end of interval h
    late = acc.components(h, h + 1, int(h + d.arrival_delay[i, h]))
    assert early.c_pending[i, 0] and not early.c_avail[i, 0]
    assert late.c_avail[i, 0] and late.c_metered[i, 0] == pytest.approx(d.meter_kwh[i, h])


def test_duplicate_records_are_not_double_counted():
    values = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    delay = np.array([[0.0, np.inf, 5.0], [0.0, 0.0, 0.0]])
    out = _ingest(values, delay, dup_rate=0.5, rng=np.random.default_rng(0))
    assert out["duplicates_removed"] == round(0.5 * 5)
    assert np.isnan(out["values"][0, 1])
    assert np.nansum(out["values"]) == pytest.approx(1 + 3 + 4 + 5 + 6)


def test_outage_hours_contribute_zero_on_both_sides():
    ctx = prepare(SimulationConfig(scenario="A", seed=3, outage_rate=2.0))
    d, acc = ctx.data, ctx.accountant
    obs_out = [o for o in d.outages if o["start_hour"] >= d.h0]
    assert obs_out, "expected at least one outage in the observation window"
    o = obs_out[0]
    f = o["feeder"]
    fi = d.feeder_ids.index(f)
    a, b = o["start_hour"], o["end_hour"]
    comp = acc.components(a, b, b + 48)
    hr = acc.hourly(comp, "feeder")
    assert np.all(d.feeder_meter_kwh[fi, a:b][np.isfinite(d.feeder_meter_kwh[fi, a:b])] == 0)
    assert np.nansum(hr["metered"][fi]) == 0 and np.nansum(hr["imputed"][fi]) == 0
    assert np.nansum(hr["loss_est"][fi]) == 0
    assert acc.balance("feeder", f, a, b, b + 48)["data_quality"]["known_outage_hours"] == b - a


def test_input_meter_gaps_are_dropped_from_both_sides(normal_ctx):
    d, acc = normal_ctx.data, normal_ctx.accountant
    gaps = np.argwhere(~np.isfinite(d.feeder_meter_kwh[:, d.h0:]))
    if len(gaps) == 0:
        pytest.skip("no input-meter gap in this seed")
    f, s = gaps[0]
    h = d.h0 + s
    b = acc.balance("feeder", d.feeder_ids[f], h - 5, h + 5, h + 10)
    assert b["window"]["hours_used"] == b["window"]["hours_in_time"] - b["data_quality"]["input_meter_gaps_h"]
    assert b["data_quality"]["input_meter_gaps_h"] >= 1


def test_loss_calibration_removes_persistent_loss_model_bias():
    biased = prepare(SimulationConfig(scenario="A", seed=4, systematic_loss_error_pct=-35, loss_calibration=False))
    calibrated = prepare(SimulationConfig(scenario="A", seed=4, systematic_loss_error_pct=-35, loss_calibration=True))
    a, b = biased.data.h0, biased.data.H
    zb = biased.accountant.balance("feeder", "F1", a, b, b - 1)["z_score"]
    zc = calibrated.accountant.balance("feeder", "F1", a, b, b - 1)["z_score"]
    assert zb > 3 and abs(zc) < 2
    assert 1.3 < calibrated.accountant.k_f[0] < 1.8
