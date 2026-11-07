# OWNER: P4 | STATUS: ACTIVE
"""T1 technical loss, simulator invariants and T2 energy balance."""

from __future__ import annotations

import json

import numpy as np
import pandapower as pp
import pytest

from cascadeguard.theft import THEFT_TYPES
from cascadeguard.theft import energy_balance as eb
from cascadeguard.theft.technical_loss import (
    FeederSpec, analytic_losses, corridor_line_losses, corridor_loss_summary,
    fit_feeder_loss_curves, run_feeder_power_flow,
)


@pytest.fixture(scope="module")
def spec(cfg):
    return FeederSpec.from_config("F_TEST", [1.0, 0.8, 1.2, 0.6], [250, 100, 250, 100], config=cfg)


def test_feeder_power_flow_is_physical(spec):
    res = run_feeder_power_flow(spec, [120.0, 40.0, 150.0, 50.0])
    assert res["input_kw"] > res["load_kw"] > 0
    assert 0.01 < res["loss_kw"] / res["input_kw"] < 0.10          # plausible distribution loss
    assert 0.90 < res["min_vm_pu"] <= 1.0


def test_analytic_losses_close_to_pandapower(spec):
    loads = np.array([120.0, 40.0, 150.0, 50.0])
    res = run_feeder_power_flow(spec, loads)
    trunk, dt = analytic_losses(spec, loads[:, None])
    assert abs((trunk[0] + dt.sum()) - res["loss_kw"]) / res["loss_kw"] < 0.15


def test_loss_curve_fit_and_monotone(spec, cfg):
    fit = fit_feeder_loss_curves(spec, np.array([120.0, 40.0, 150.0, 50.0]), cfg["feeder_electrical"]["fit_scales"])
    assert fit["feeder"].max_rel_error < 0.05
    p = np.linspace(fit["feeder"].p_min_kw, fit["feeder"].p_max_kw, 20)
    assert np.all(np.diff(fit["feeder"].predict(p)) > 0)          # more load -> more loss
    assert 0.9 < fit["trunk_factor"] < 1.3


def test_corridor_losses_from_p1_model():
    from cascadeguard.grid.corridor_model import build_corridor_network
    net = build_corridor_network()
    pp.runpp(net, algorithm="nr", init="dc", numba=False)
    sec = corridor_line_losses(net)
    summary = corridor_loss_summary(net)
    assert len(sec) == 38 and (sec.loss_mw >= 0).all()
    assert 0.5 < summary["transmission_loss_pct"] < 8.0


def test_simulator_invariants(ds):
    c = ds.consumers
    assert set(THEFT_TYPES) <= set(c.theft_type)
    assert ds.metered_kwh.shape == ds.true_kwh.shape == (len(c), ds.n_periods)
    met = np.nan_to_num(ds.metered_kwh, nan=0.0)
    assert (met <= ds.true_kwh + 1e-4).all()                       # meters never over-read
    assert (ds.ntl_kwh[c.theft_type.to_numpy() == "none"].sum(axis=1) < 1e-3).all()
    assert (ds.ntl_kwh[:, :ds.history_end].sum() < 1e-6)            # theft only in scoring window
    assert c.groupby("consumer_id").split.nunique().max() == 1
    assert c.consumer_id.str.match(r"^C\d{7}$").all()


def test_meter_frame_follows_p2_contract(ds):
    schema = json.load(open("contracts/meter_data.schema.json", encoding="utf-8"))
    frame = ds.to_meter_frame(ds.consumers.consumer_id.head(3).tolist())
    assert list(frame.columns) == list(schema["properties"])
    assert set(frame.theft_type) <= set(schema["properties"]["theft_type"]["enum"])
    assert set(frame.split) <= set(schema["properties"]["split"]["enum"])
    assert (frame.metered_kwh >= 0).all() and frame.metered_kwh.notna().all()


def test_save_load_roundtrip(ds, tmp_path):
    ds.save(tmp_path / "d")
    back = type(ds).load(tmp_path / "d")
    assert np.allclose(np.nan_to_num(back.metered_kwh), np.nan_to_num(ds.metered_kwh))
    assert back.curves[ds.feeders.feeder_id[0]]["feeder"].a == pytest.approx(ds.curves[ds.feeders.feeder_id[0]]["feeder"].a)


def test_energy_balance_estimates(ds, balances):
    fb, _ = balances
    split = eb.loss_split(ds, fb, "recent")
    assert abs(split["technical_loss_est_error_pct_points"]) < 0.3
    hist = eb.loss_split(ds, fb, "history")
    assert hist["ntl_pct_true"] == pytest.approx(0.0, abs=1e-9)
    ratio = eb.ntl_ratio_by_substation(ds, fb)
    assert (ratio.est_ntl_ratio >= 0).all()
    assert np.corrcoef(ratio.est_ntl_ratio, ratio.true_ntl_ratio)[0, 1] > 0.5


def test_residual_change_ranks_theft_feeders(ds, balances):
    fb, db = balances
    truth = eb.true_ntl_by_node(ds, "feeder_id")
    loc = eb.localisation_accuracy(fb.summary, truth, top_n=3)
    assert loc["top_n_precision"] >= 0.66
    assert not db.summary.empty and db.summary.node_id.isin(ds.dts.dt_id[ds.dts.metered]).all()
    heat = eb.residual_heatmap(fb)
    assert heat.shape[0] == len(ds.feeders)
