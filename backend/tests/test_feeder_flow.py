"""Validates the vectorised backward/forward-sweep solver against pandapower (Newton-Raphson)."""

import numpy as np
import pytest

from gridwatch.simulation.feeder_flow import FeederSolver
from gridwatch.simulation.grid_snapshot import HAVE_PANDAPOWER, GridSnapshotModel, build_net
from gridwatch.simulation.topology import TopologyConfig, build_topology

pp = pytest.importorskip("pandapower")


@pytest.mark.parametrize("loading", [0.2, 0.6, 1.1])
def test_bfs_matches_pandapower(loading):
    """Head P/Q within 0.05 %/0.5 %, losses within 1 %, voltages within 5e-4 pu. The small LV
    voltage difference comes from transformer modelling: pandapower's T-model places the
    magnetising branch mid-impedance, the sweep solver places it on the HV terminal."""
    topo = build_topology(TopologyConfig())
    rng = np.random.default_rng(0)
    net, bus_idx, line_idx, trafo_idx, load_idx = build_net(topo, distribution_only=True)
    loads = {}
    for dt in topo.dts.values():
        p = loading * rng.uniform(0.7, 1.0) * dt.sn_kva / 1000.0 * 0.93
        loads[dt.id] = (p, p * 0.4)
        net.load.at[load_idx[dt.id], "p_mw"] = p
        net.load.at[load_idx[dt.id], "q_mvar"] = p * 0.4
    pp.runpp(net, numba=False, tolerance_mva=1e-10)

    for fid, fd in topo.feeders.items():
        solver = FeederSolver(topo, fid)
        p = np.array([[loads[d][0]] for d in solver.dt_ids])
        q = np.array([[loads[d][1]] for d in solver.dt_ids])
        res = solver.solve(p, q)
        head = net.res_line.loc[line_idx[fd.head_branch]]
        assert res.p_head_mw[0] == pytest.approx(head.p_from_mw, rel=5e-4)
        assert res.q_head_mvar[0] == pytest.approx(head.q_from_mvar, rel=5e-3)
        pp_loss = sum(net.res_line.loc[line_idx[b], "pl_mw"] for b in fd.mv_branches)
        for d in fd.dts:
            pp_loss += net.res_trafo.loc[trafo_idx[topo.dts[d].trafo_branch], "pl_mw"]
            pp_loss += net.res_line.loc[line_idx[topo.dts[d].lv_branch], "pl_mw"]
        assert res.total_loss_mw[0] == pytest.approx(pp_loss, rel=1e-2)
        for d in fd.dts:
            v_pp = net.res_bus.loc[bus_idx[topo.dts[d].group_bus], "vm_pu"]
            assert res.v_pu[topo.dts[d].group_bus][0] == pytest.approx(v_pp, abs=5e-4)


def test_energy_conservation_in_bfs():
    """Head power must equal demand plus losses (no energy created or destroyed)."""
    topo = build_topology(TopologyConfig())
    solver = FeederSolver(topo, "F1")
    rng = np.random.default_rng(3)
    p = rng.uniform(0.01, 0.2, size=(3, 48))
    res = solver.solve(p, p * 0.3)
    assert np.allclose(res.p_head_mw, p.sum(axis=0) + res.total_loss_mw, rtol=1e-9, atol=1e-12)


def test_deenergised_steps_are_zero():
    topo = build_topology(TopologyConfig())
    solver = FeederSolver(topo, "F2")
    p = np.full((3, 4), 0.05)
    on = np.array([True, False, True, False])
    res = solver.solve(p, p * 0.3, energised=on)
    assert np.all(res.p_head_mw[~on] == 0) and np.all(res.p_head_mw[on] > 0)


@pytest.mark.skipif(not HAVE_PANDAPOWER, reason="pandapower missing")
def test_full_network_snapshot_converges():
    topo = build_topology(TopologyConfig())
    model = GridSnapshotModel(topo)
    res = model.solve(19, 2, {d: 0.05 for d in topo.dt_ids}, {d: 0.02 for d in topo.dt_ids},
                      {f: True for f in topo.feeder_ids})
    assert res["converged"]
    # Power balance of the whole network: slack + generation = loads + losses.
    total_load = 0.05 * len(topo.dt_ids) + res["other_66kv_load_mw"]
    assert res["slack_p_mw"] + res["gen_p_mw"] == pytest.approx(total_load + res["total_loss_mw"], rel=1e-6)


@pytest.mark.skipif(not HAVE_PANDAPOWER, reason="pandapower missing")
def test_snapshot_survives_outage_and_restoration():
    """Regression: an outage isolates buses (NaN voltages); later solves must not warm-start from them."""
    topo = build_topology(TopologyConfig())
    model = GridSnapshotModel(topo)
    p = {d: 0.05 for d in topo.dt_ids}
    q = {d: 0.02 for d in topo.dt_ids}
    on = {f: True for f in topo.feeder_ids}
    for energised in (on, {**on, "F3": False}, {**on, "F3": False}, on, on):
        res = model.solve(19, 2, p, q, energised)
        assert res["converged"]
        assert res["branches"]["F3-MV1"]["in_service"] == energised["F3"]
