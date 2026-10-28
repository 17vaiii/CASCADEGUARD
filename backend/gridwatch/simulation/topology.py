"""Illustrative network topology.

The model follows the generic chain

    hydro generation -> interconnected 220 kV network -> 220/66 kV receiving station
    -> 66/11 kV distribution substation -> 11 kV feeders -> distribution transformers (DTs)
    -> LV networks -> consumer groups (smart meters)

Only the *names* "Sharavathi" and "SRS Peenya" are anchored to public sources (see
docs/research/source-note.md). Every line length, rating, impedance and the topology
itself are illustrative engineering assumptions. In particular, the model does NOT
claim a dedicated Sharavathi -> Peenya line: the generator and the receiving station
are connected through a meshed, interconnected 220 kV network with a slack bus that
stands for the rest of the grid.

This module is pure data (no pandapower import) so that it can be used by the fast
vectorised feeder solver, the pandapower snapshot builder and the API alike.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Provenance = Literal["public-source", "illustrative", "assumption"]
FeederArchetype = Literal["industrial", "mixed", "residential"]

ARCHETYPE_CYCLE: tuple[FeederArchetype, ...] = (
    "industrial",
    "mixed",
    "residential",
    "residential",
    "mixed",
    "industrial",
)

# Typical-value DT and LV parameters per feeder archetype (assumptions, not utility data).
# Residential LV networks are long and lightly loaded; industrial ones short and heavy.
DT_PARAMS: dict[str, dict[str, float]] = {
    # sn_kva, vk%, vkr%, no-load loss kW, magnetising current %
    "industrial": {"sn_kva": 400.0, "vk_percent": 4.5, "vkr_percent": 1.15, "pfe_kw": 0.75, "i0_percent": 1.2},
    "mixed": {"sn_kva": 160.0, "vk_percent": 4.0, "vkr_percent": 1.4, "pfe_kw": 0.40, "i0_percent": 1.6},
    "residential": {"sn_kva": 100.0, "vk_percent": 4.0, "vkr_percent": 1.6, "pfe_kw": 0.26, "i0_percent": 1.8},
}
LV_PARAMS: dict[str, dict[str, float]] = {
    # Equivalent single-branch representation of the LV distributor (assumption).
    "industrial": {"r_ohm_per_km": 0.10, "x_ohm_per_km": 0.08, "length_km": 0.30, "max_i_ka": 0.80},
    "mixed": {"r_ohm_per_km": 0.30, "x_ohm_per_km": 0.09, "length_km": 0.35, "max_i_ka": 0.35},
    "residential": {"r_ohm_per_km": 0.55, "x_ohm_per_km": 0.10, "length_km": 0.40, "max_i_ka": 0.20},
}
# 11 kV overhead conductor with ACSR "Rabbit"-class values (typical published values).
MV_LINE = {"r_ohm_per_km": 0.5426, "x_ohm_per_km": 0.349, "c_nf_per_km": 0.0, "max_i_ka": 0.193}
MV_SEGMENT_KM = (2.2, 1.8, 1.5, 1.3)  # segment lengths along each feeder (illustrative)

LV_KV = 0.433  # DT secondary nominal voltage used as the LV base
MV_KV = 11.0


@dataclass
class Bus:
    id: str
    label: str
    vn_kv: float
    kind: str  # grid | generator | transmission | receiving | distribution | mv_junction | dt_lv | consumer_group
    x: float
    y: float
    provenance: Provenance
    description: str
    feeder: str | None = None
    dt: str | None = None


@dataclass
class Branch:
    id: str
    kind: Literal["line", "trafo"]
    from_bus: str
    to_bus: str
    label: str
    provenance: Provenance
    params: dict[str, float]
    feeder: str | None = None
    dt: str | None = None
    parallel: int = 1
    std_type: str | None = None


@dataclass
class Meter:
    id: str
    kind: Literal["feeder_head", "dt", "consumer_group"]
    label: str
    location: str  # bus id (for consumer groups) or branch id (for feeder/DT meters)
    accuracy_class: str
    feeder: str | None = None
    dt: str | None = None


@dataclass
class DistributionTransformer:
    id: str
    feeder: str
    index: int
    hv_bus: str
    lv_bus: str
    group_bus: str
    trafo_branch: str
    lv_branch: str
    archetype: FeederArchetype
    sn_kva: float


@dataclass
class Feeder:
    id: str
    label: str
    archetype: FeederArchetype
    head_branch: str
    mv_branches: list[str]
    dts: list[str]


@dataclass
class TopologyConfig:
    n_feeders: int = 4
    dts_per_feeder: int = 3
    consumers_per_dt: int = 25

    def validate(self) -> None:
        if not 2 <= self.n_feeders <= 6:
            raise ValueError("n_feeders must be between 2 and 6")
        if not 2 <= self.dts_per_feeder <= 4:
            raise ValueError("dts_per_feeder must be between 2 and 4")
        if not 5 <= self.consumers_per_dt <= 80:
            raise ValueError("consumers_per_dt must be between 5 and 80")


@dataclass
class Topology:
    config: TopologyConfig
    buses: dict[str, Bus] = field(default_factory=dict)
    branches: dict[str, Branch] = field(default_factory=dict)
    meters: dict[str, Meter] = field(default_factory=dict)
    feeders: dict[str, Feeder] = field(default_factory=dict)
    dts: dict[str, DistributionTransformer] = field(default_factory=dict)

    @property
    def feeder_ids(self) -> list[str]:
        return list(self.feeders)

    @property
    def dt_ids(self) -> list[str]:
        return list(self.dts)

    def to_api(self) -> dict:
        return {
            "config": asdict(self.config),
            "buses": [asdict(b) for b in self.buses.values()],
            "branches": [asdict(b) for b in self.branches.values()],
            "meters": [asdict(m) for m in self.meters.values()],
            "feeders": [asdict(f) for f in self.feeders.values()],
            "dts": [asdict(d) for d in self.dts.values()],
        }


def build_topology(cfg: TopologyConfig | None = None) -> Topology:
    cfg = cfg or TopologyConfig()
    cfg.validate()
    topo = Topology(config=cfg)

    def bus(**kw) -> None:
        b = Bus(**kw)
        topo.buses[b.id] = b

    def branch(**kw) -> None:
        br = Branch(**kw)
        topo.branches[br.id] = br

    # ---- Generation and interconnected transmission (illustrative) -----------------
    bus(id="GRID220", label="Interconnected grid (slack)", vn_kv=220.0, kind="grid", x=0, y=-40,
        provenance="assumption",
        description="Equivalent of the rest of the interconnected KPTCL / Southern Region network. "
                    "Modelled as the power-flow slack bus; it balances generation and load.")
    bus(id="HYD220", label="Hydro source (Sharavathi-inspired)", vn_kv=220.0, kind="generator", x=0, y=330,
        provenance="public-source",
        description="Stands in for a large hydroelectric station such as KPCL's 1035 MW Sharavathi "
                    "Generating Station (10 x 103.5 MW, public sources). Dispatch values in this model "
                    "are illustrative, not the station's actual schedule.")
    bus(id="TXA220", label="220 kV transmission node", vn_kv=220.0, kind="transmission", x=300, y=145,
        provenance="illustrative",
        description="Illustrative intermediate 220 kV substation of the meshed transmission network.")
    bus(id="SRS220", label="Receiving station 220 kV", vn_kv=220.0, kind="receiving", x=600, y=145,
        provenance="public-source",
        description="Inspired by KPTCL's 220/66/11 kV Sharavathi Receiving Station (SRS), Peenya, "
                    "Bengaluru (public sources). Ratings and connections here are illustrative.")
    bus(id="SRS66", label="Receiving station 66 kV", vn_kv=66.0, kind="receiving", x=830, y=145,
        provenance="illustrative", description="66 kV bus of the receiving station (illustrative).")
    bus(id="DSS66", label="Distribution substation 66 kV", vn_kv=66.0, kind="distribution", x=1060, y=145,
        provenance="illustrative", description="66 kV side of an illustrative 66/11 kV distribution substation.")
    bus(id="DSS11", label="Distribution substation 11 kV", vn_kv=11.0, kind="distribution", x=1280, y=145,
        provenance="illustrative",
        description="11 kV bus feeding the distribution feeders; feeder-head energy meters sit on its outgoing bays.")

    line220 = "490-AL1/64-ST1A 220.0"
    for bid, a, b, km in (
        ("L220-HYD-TXA", "HYD220", "TXA220", 120.0),
        ("L220-TXA-SRS", "TXA220", "SRS220", 140.0),
        ("L220-GRID-TXA", "GRID220", "TXA220", 90.0),
        ("L220-GRID-SRS", "GRID220", "SRS220", 70.0),
    ):
        branch(id=bid, kind="line", from_bus=a, to_bus=b, label=f"220 kV line {a[:-3]}-{b[:-3]} ({km:.0f} km, illustrative)",
               provenance="illustrative", params={"length_km": km}, parallel=2, std_type=line220)

    branch(id="T220-66", kind="trafo", from_bus="SRS220", to_bus="SRS66", label="2 x 100 MVA 220/66 kV transformers",
           provenance="illustrative", parallel=2,
           params={"sn_mva": 100.0, "vn_hv_kv": 220.0, "vn_lv_kv": 66.0, "vk_percent": 12.5,
                   "vkr_percent": 0.30, "pfe_kw": 45.0, "i0_percent": 0.05})
    branch(id="L66-SRS-DSS", kind="line", from_bus="SRS66", to_bus="DSS66", label="66 kV line (6 km, illustrative)",
           provenance="illustrative",
           params={"length_km": 6.0, "r_ohm_per_km": 0.19, "x_ohm_per_km": 0.39, "c_nf_per_km": 9.5, "max_i_ka": 0.45})
    branch(id="T66-11", kind="trafo", from_bus="DSS66", to_bus="DSS11", label="20 MVA 66/11 kV transformer",
           provenance="illustrative",
           params={"sn_mva": 20.0, "vn_hv_kv": 66.0, "vn_lv_kv": 11.0, "vk_percent": 10.0,
                   "vkr_percent": 0.6, "pfe_kw": 14.0, "i0_percent": 0.08})

    # ---- 11 kV feeders, DTs and consumer groups ---------------------------------------
    n_f, n_dt = cfg.n_feeders, cfg.dts_per_feeder
    row_gap = 250.0
    for fi in range(n_f):
        fid = f"F{fi + 1}"
        arch = ARCHETYPE_CYCLE[fi % len(ARCHETYPE_CYCLE)]
        y = 145 + (fi - (n_f - 1) / 2) * row_gap
        mv_branches: list[str] = []
        dt_ids: list[str] = []
        prev = "DSS11"
        for k in range(n_dt):
            jid = f"{fid}J{k + 1}"
            x = 1540 + k * 330
            bus(id=jid, label=f"{fid} pole/junction {k + 1}", vn_kv=MV_KV, kind="mv_junction", x=x, y=y,
                provenance="illustrative", description=f"11 kV tapping point on feeder {fid}.", feeder=fid)
            seg = f"{fid}-MV{k + 1}"
            km = MV_SEGMENT_KM[k % len(MV_SEGMENT_KM)]
            branch(id=seg, kind="line", from_bus=prev, to_bus=jid,
                   label=f"{fid} 11 kV segment {k + 1} ({km} km)", provenance="assumption",
                   params={"length_km": km, **MV_LINE}, feeder=fid)
            mv_branches.append(seg)
            prev = jid

            dtid = f"{fid}-DT{k + 1}"
            lv_bus, grp_bus = f"{dtid}-LV", f"{dtid}-GRP"
            p = DT_PARAMS[arch]
            bus(id=lv_bus, label=f"{dtid} LV side", vn_kv=LV_KV, kind="dt_lv", x=x + 95, y=y + 70,
                provenance="assumption", description=f"Secondary (433 V) side of {dtid}; DT energy meter location.",
                feeder=fid, dt=dtid)
            bus(id=grp_bus, label=f"{dtid} consumers", vn_kv=LV_KV, kind="consumer_group", x=x + 190, y=y + 70,
                provenance="assumption",
                description=f"Aggregation point for the synthetic smart-metered consumers supplied by {dtid}.",
                feeder=fid, dt=dtid)
            tb = f"{dtid}-TR"
            branch(id=tb, kind="trafo", from_bus=jid, to_bus=lv_bus,
                   label=f"{dtid} {p['sn_kva']:.0f} kVA 11/0.433 kV", provenance="assumption",
                   params={"sn_mva": p["sn_kva"] / 1000.0, "vn_hv_kv": MV_KV, "vn_lv_kv": LV_KV,
                           "vk_percent": p["vk_percent"], "vkr_percent": p["vkr_percent"],
                           "pfe_kw": p["pfe_kw"], "i0_percent": p["i0_percent"]},
                   feeder=fid, dt=dtid)
            lvb = f"{dtid}-LVN"
            branch(id=lvb, kind="line", from_bus=lv_bus, to_bus=grp_bus, label=f"{dtid} LV distributor (equivalent)",
                   provenance="assumption", params={**LV_PARAMS[arch], "c_nf_per_km": 0.0}, feeder=fid, dt=dtid)
            topo.dts[dtid] = DistributionTransformer(
                id=dtid, feeder=fid, index=k, hv_bus=jid, lv_bus=lv_bus, group_bus=grp_bus,
                trafo_branch=tb, lv_branch=lvb, archetype=arch, sn_kva=p["sn_kva"])
            dt_ids.append(dtid)
            topo.meters[f"M-{dtid}"] = Meter(id=f"M-{dtid}", kind="dt", label=f"DT meter {dtid}", location=lvb,
                                             accuracy_class="0.5S", feeder=fid, dt=dtid)
            topo.meters[f"M-{dtid}-C"] = Meter(id=f"M-{dtid}-C", kind="consumer_group",
                                               label=f"Consumer smart meters {dtid}", location=grp_bus,
                                               accuracy_class="1.0", feeder=fid, dt=dtid)

        topo.feeders[fid] = Feeder(id=fid, label=f"Feeder {fid} ({arch})", archetype=arch,
                                   head_branch=mv_branches[0], mv_branches=mv_branches, dts=dt_ids)
        topo.meters[f"M-{fid}"] = Meter(id=f"M-{fid}", kind="feeder_head", label=f"Feeder-head meter {fid}",
                                        location=mv_branches[0], accuracy_class="0.5S", feeder=fid)

    # Aggregate of all other load served from the receiving station's 66 kV bus.
    bus(id="OTHER66", label="Other 66 kV load (aggregate)", vn_kv=66.0, kind="aggregate_load", x=830, y=360,
        provenance="assumption",
        description="Lumped equivalent of the load of all substations not modelled in detail.")
    branch(id="L66-OTHER", kind="line", from_bus="SRS66", to_bus="OTHER66", label="Aggregate 66 kV connection",
           provenance="assumption",
           params={"length_km": 0.1, "r_ohm_per_km": 0.05, "x_ohm_per_km": 0.1, "c_nf_per_km": 0.0, "max_i_ka": 2.0})
    return topo
