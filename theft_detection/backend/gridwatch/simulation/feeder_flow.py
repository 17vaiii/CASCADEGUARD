"""Vectorised backward/forward-sweep (BFS) power flow for radial 11 kV feeders.

Solves every time step of a feeder simultaneously (arrays shaped [node, time]) so that
the energy-accounting layer can obtain physically consistent feeder-head energy, DT
energy and technical losses for weeks of hourly data in milliseconds. The solver is
validated against pandapower's Newton-Raphson solution in tests/test_feeder_flow.py.

Model (per feeder):
  root  = 11 kV substation bus, voltage fixed at `v_root_pu` (OLTC-regulated assumption)
  MV    = series 11 kV segments (lines, no shunt capacitance)
  DT    = series impedance from vk%/vkr% + constant-impedance magnetising/core shunt at HV side
  LV    = one equivalent LV distributor per DT
  loads = constant-power P+jQ at each consumer-group bus
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .topology import Topology

S_BASE_MVA = 1.0


@dataclass
class _Branch:
    id: str
    parent: int
    child: int
    z: complex  # per-unit series impedance
    i_base_ka: float
    rating: float  # max_i_ka for lines, sn_mva for trafos
    kind: str


@dataclass
class FeederFlowResult:
    feeder: str
    branch_ids: list[str]
    branch_kind: list[str]
    p_head_mw: np.ndarray  # [T] active power entering the feeder at the substation bus
    q_head_mvar: np.ndarray
    p_dt_lv_mw: np.ndarray  # [n_dt, T] power leaving each DT secondary into its LV network
    branch_loss_mw: np.ndarray  # [n_branch, T] series (I^2 R) losses
    core_loss_mw: np.ndarray  # [n_dt, T] DT no-load (core) losses
    branch_i_ka: np.ndarray  # [n_branch, T]
    branch_loading_pct: np.ndarray  # [n_branch, T]
    v_pu: dict[str, np.ndarray]  # bus id -> [T]
    iterations: int

    @property
    def total_loss_mw(self) -> np.ndarray:
        return self.branch_loss_mw.sum(axis=0) + self.core_loss_mw.sum(axis=0)

    def mv_loss_mw(self) -> np.ndarray:
        idx = [i for i, k in enumerate(self.branch_kind) if k == "mv"]
        return self.branch_loss_mw[idx].sum(axis=0)


class FeederSolver:
    """Pre-computes the per-unit model of one feeder; `solve` can be called repeatedly."""

    def __init__(self, topo: Topology, feeder_id: str, v_root_pu: float = 1.0):
        self.topo = topo
        self.feeder = topo.feeders[feeder_id]
        self.v_root = v_root_pu
        self.dt_ids = list(self.feeder.dts)
        nodes = ["DSS11"]
        self.branches: list[_Branch] = []
        self.shunt_y: dict[int, complex] = {}

        def idx(bus_id: str) -> int:
            if bus_id not in nodes:
                nodes.append(bus_id)
            return nodes.index(bus_id)

        for seg_id in self.feeder.mv_branches:
            br = topo.branches[seg_id]
            p = br.params
            vb = topo.buses[br.to_bus].vn_kv
            zb = vb**2 / S_BASE_MVA
            z = complex(p["r_ohm_per_km"], p["x_ohm_per_km"]) * p["length_km"] / br.parallel / zb
            self.branches.append(_Branch(seg_id, idx(br.from_bus), idx(br.to_bus), z,
                                         S_BASE_MVA / (np.sqrt(3) * vb), p["max_i_ka"], "mv"))
        for dt_id in self.dt_ids:
            dt = topo.dts[dt_id]
            tr = topo.branches[dt.trafo_branch]
            p = tr.params
            sn = p["sn_mva"]
            z_mag = p["vk_percent"] / 100.0 * S_BASE_MVA / sn
            r = p["vkr_percent"] / 100.0 * S_BASE_MVA / sn
            z = complex(r, np.sqrt(max(z_mag**2 - r**2, 0.0)))
            vb = p["vn_lv_kv"]
            self.branches.append(_Branch(tr.id, idx(dt.hv_bus), idx(dt.lv_bus), z,
                                         S_BASE_MVA / (np.sqrt(3) * vb), sn, "dt"))
            pfe = p["pfe_kw"] / 1000.0
            s0 = p["i0_percent"] / 100.0 * sn
            q0 = np.sqrt(max(s0**2 - pfe**2, 0.0))
            # Shunt admittance Y in pu with S_shunt = conj(Y)|V|^2 = (pfe + j q0)|V|^2 (inductive)
            self.shunt_y[idx(dt.hv_bus)] = complex(pfe, -q0) / S_BASE_MVA
            lv = topo.branches[dt.lv_branch]
            lp = lv.params
            vb_lv = topo.buses[lv.to_bus].vn_kv
            zb = vb_lv**2 / S_BASE_MVA
            z = complex(lp["r_ohm_per_km"], lp["x_ohm_per_km"]) * lp["length_km"] / lv.parallel / zb
            self.branches.append(_Branch(lv.id, idx(lv.from_bus), idx(lv.to_bus), z,
                                         S_BASE_MVA / (np.sqrt(3) * vb_lv), lp["max_i_ka"], "lv"))
        self.nodes = nodes
        self.n = len(nodes)
        self.group_idx = [nodes.index(topo.dts[d].group_bus) for d in self.dt_ids]
        self.lv_branch_pos = [next(i for i, b in enumerate(self.branches) if b.id == topo.dts[d].lv_branch)
                              for d in self.dt_ids]
        self.hv_idx = [nodes.index(topo.dts[d].hv_bus) for d in self.dt_ids]
        self.children: list[list[int]] = [[] for _ in range(self.n)]
        for bi, b in enumerate(self.branches):
            self.children[b.parent].append(bi)

    def solve(self, p_group_mw: np.ndarray, q_group_mvar: np.ndarray, tol: float = 1e-9,
              max_iter: int = 60, energised: np.ndarray | None = None) -> FeederFlowResult:
        """p_group_mw/q_group_mvar: [n_dt, T] constant-power demand at each consumer-group bus.

        `energised` ([T] bool) marks supply interruptions; de-energised steps return zeros.
        """
        p_group_mw = np.atleast_2d(p_group_mw)
        q_group_mvar = np.atleast_2d(q_group_mvar)
        T = p_group_mw.shape[1]
        s_load = np.zeros((self.n, T), dtype=complex)
        for k, gi in enumerate(self.group_idx):
            s_load[gi] = (p_group_mw[k] + 1j * q_group_mvar[k]) / S_BASE_MVA
        y_sh = np.zeros(self.n, dtype=complex)
        for ni, y in self.shunt_y.items():
            y_sh[ni] = y
        V = np.full((self.n, T), self.v_root, dtype=complex)
        nb = len(self.branches)
        I_br = np.zeros((nb, T), dtype=complex)
        it = 0
        for it in range(1, max_iter + 1):  # noqa: B007 - `it` is reported after the loop
            I_node = np.conj(s_load / V) + y_sh[:, None] * V
            for bi in range(nb - 1, -1, -1):
                b = self.branches[bi]
                acc = I_node[b.child].copy()
                for cb in self.children[b.child]:
                    acc += I_br[cb]
                I_br[bi] = acc
            V_new = V.copy()
            V_new[0] = self.v_root
            for bi, b in enumerate(self.branches):
                V_new[b.child] = V_new[b.parent] - b.z * I_br[bi]
            delta = np.max(np.abs(V_new - V))
            V = V_new
            if delta < tol:
                break

        head = [bi for bi, b in enumerate(self.branches) if b.parent == 0]
        I_head = I_br[head].sum(axis=0)
        s_head = V[0] * np.conj(I_head) * S_BASE_MVA
        losses = np.array([np.abs(I_br[bi]) ** 2 * self.branches[bi].z.real for bi in range(nb)]) * S_BASE_MVA
        core = np.array([y_sh[h].real * np.abs(V[h]) ** 2 for h in self.hv_idx]) * S_BASE_MVA
        p_dt_lv = np.array([(V[self.branches[bi].parent] * np.conj(I_br[bi])).real for bi in self.lv_branch_pos])
        i_ka = np.array([np.abs(I_br[bi]) * self.branches[bi].i_base_ka for bi in range(nb)])
        loading = np.zeros_like(i_ka)
        for bi, b in enumerate(self.branches):
            if b.kind == "dt":
                s_mva = np.abs(V[b.child] * np.conj(I_br[bi])) * S_BASE_MVA
                loading[bi] = 100.0 * s_mva / b.rating
            else:
                loading[bi] = 100.0 * i_ka[bi] / b.rating

        p_head, q_head = s_head.real, s_head.imag
        if energised is not None:
            off = ~np.asarray(energised, dtype=bool)
            for arr in (p_head, q_head):
                arr[off] = 0.0
            for arr in (losses, core, p_dt_lv, i_ka, loading):
                arr[:, off] = 0.0
        return FeederFlowResult(
            feeder=self.feeder.id,
            branch_ids=[b.id for b in self.branches],
            branch_kind=[b.kind for b in self.branches],
            p_head_mw=p_head,
            q_head_mvar=q_head,
            p_dt_lv_mw=p_dt_lv,
            branch_loss_mw=losses,
            core_loss_mw=core,
            branch_i_ka=i_ka,
            branch_loading_pct=loading,
            v_pu={self.nodes[i]: np.abs(V[i]) for i in range(self.n)},
            iterations=it,
        )
