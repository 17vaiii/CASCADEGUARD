"""Synthetic dataset generator.

Pipeline for one simulation run (all hourly, H = history + observation hours):

  consumers & categories -> true electrical demand (kW = kWh per hour)
  -> benign events (genuine consumption drops, supply outages)
  -> scenario injections (recorded-consumption deviation, unmetered load, data faults, ...)
  -> radial power flow per feeder (feeder-head energy, DT energy, technical losses)
  -> meter models (bias + random error + quantisation)
  -> communication model (delay / loss / duplicate records) -> ingestion (de-duplication)

Random numbers come from independent named streams derived from the seed, so the same
seed produces identical background data with or without an injection. This makes
"scenario vs. normal operation" comparisons exact and resets reproducible.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass, field

import numpy as np

from ..config import HISTORY_DAYS, OBSERVATION_DAYS
from . import profiles as P
from .feeder_flow import FeederSolver
from .scenarios import THEFT_LIKE, Injection, SimulationConfig
from .topology import Topology, TopologyConfig, build_topology

# Indicative distribution-transformer data: kVA -> (no-load loss kW, full-load copper loss kW, vk %, i0 %).
# Order of magnitude of Indian standard-efficiency DTs; an assumption, not a utility dataset.
DT_STANDARD_RATINGS = {
    63: (0.18, 1.00, 4.5, 2.0),
    100: (0.26, 1.50, 4.5, 1.8),
    160: (0.37, 2.10, 4.5, 1.6),
    250: (0.52, 3.00, 4.5, 1.5),
    315: (0.60, 3.60, 4.5, 1.4),
    400: (0.75, 4.30, 4.5, 1.3),
    500: (0.85, 5.00, 4.5, 1.2),
    630: (1.00, 6.00, 4.5, 1.2),
}
DT_TARGET_PEAK_LOADING = 0.70

# Meter error model (relative). Bias is fixed per meter per run; random error per reading.
METER_ERROR = {
    "feeder_head": {"bias": 0.003, "random": 0.002, "missing": 0.001},
    "dt": {"bias": 0.004, "random": 0.003, "missing": 0.003},
    "consumer": {"bias": 0.0025, "random": 0.004},
}


def rng_for(seed: int, *names: str | int) -> np.random.Generator:
    key = [seed] + [zlib.crc32(str(n).encode()) for n in names]
    return np.random.default_rng(key)


@dataclass
class ResolvedEvent:
    """An injection after it has been resolved to concrete targets (simulation ground truth)."""

    index: int
    type: str
    theft_like: bool
    feeder: str
    dt: str | None
    consumers: list[str]
    magnitude: float
    start_hour: int  # absolute hour index
    end_hour: int  # exclusive
    detail: dict = field(default_factory=dict)


@dataclass
class SimulationData:
    config: SimulationConfig
    topo: Topology
    H: int
    h0: int  # absolute index of the first observation hour (timeline step 0)
    hod: np.ndarray
    dow: np.ndarray
    consumer_ids: np.ndarray
    consumer_category: np.ndarray
    consumer_dt_idx: np.ndarray
    consumer_feeder_idx: np.ndarray
    true_kwh: np.ndarray  # [C, H] energy actually drawn
    recorded_kwh: np.ndarray  # [C, H] energy the meter registers before measurement error
    meter_kwh: np.ndarray  # [C, H] ingested reading (NaN if never received)
    arrival_delay: np.ndarray  # [C, H] hours after interval end until available (inf = never)
    unmetered_kw: np.ndarray  # [n_dt, H]
    energised: np.ndarray  # [n_f, H]
    feeder_true_kwh: np.ndarray  # [n_f, H]
    feeder_meter_kwh: np.ndarray  # [n_f, H] NaN = missing
    dt_true_kwh: np.ndarray  # [n_dt, H]
    dt_meter_kwh: np.ndarray  # [n_dt, H]
    true_loss_kwh: dict[str, np.ndarray]  # per feeder: "mv","dt_cu","dt_core","lv" -> [n_f, H]; "lv_dt" -> [n_dt, H]
    loss_estimate_factor: np.ndarray  # [n_f, H] multiplier applied to the utility loss estimate
    noise_mult: np.ndarray  # [n_f, H]
    label_theft_consumer: np.ndarray  # [C, H] bool
    label_benign_change: np.ndarray  # [C, H] bool
    label_data_fault: np.ndarray  # [C, H] bool
    label_unmetered_dt: np.ndarray  # [n_dt, H] bool
    events: list[ResolvedEvent]
    benign_events: list[dict]
    outages: list[dict]
    ingestion: dict
    branch_loading_pct: dict[str, np.ndarray]  # branch id -> [H]
    bus_v_pu: dict[str, np.ndarray]
    data_hash: str = ""

    # ---- convenience -------------------------------------------------------------------
    @property
    def feeder_ids(self) -> list[str]:
        return self.topo.feeder_ids

    @property
    def dt_ids(self) -> list[str]:
        return self.topo.dt_ids

    @property
    def n_steps(self) -> int:
        return self.H - self.h0

    def dt_feeder_idx(self) -> np.ndarray:
        fids = self.feeder_ids
        return np.array([fids.index(self.topo.dts[d].feeder) for d in self.dt_ids])

    def label_theft_dt(self) -> np.ndarray:
        n_dt = len(self.dt_ids)
        out = self.label_unmetered_dt.copy()
        for k in range(n_dt):
            m = self.consumer_dt_idx == k
            if m.any():
                out[k] |= self.label_theft_consumer[m].any(axis=0)
        return out

    def label_theft_feeder(self) -> np.ndarray:
        dt_lab = self.label_theft_dt()
        f_of_dt = self.dt_feeder_idx()
        return np.array([dt_lab[f_of_dt == f].any(axis=0) for f in range(len(self.feeder_ids))])


def _choose_dt_rating(peak_kva: float) -> int:
    for kva in sorted(DT_STANDARD_RATINGS):
        if peak_kva <= DT_TARGET_PEAK_LOADING * kva:
            return kva
    return max(DT_STANDARD_RATINGS)


def _apply_dt_rating(topo: Topology, dt_id: str, kva: int) -> None:
    pfe, pcu, vk, i0 = DT_STANDARD_RATINGS[kva]
    dt = topo.dts[dt_id]
    dt.sn_kva = float(kva)
    br = topo.branches[dt.trafo_branch]
    br.params.update({"sn_mva": kva / 1000.0, "vk_percent": vk, "vkr_percent": 100.0 * pcu / kva,
                      "pfe_kw": pfe, "i0_percent": i0})
    br.label = f"{dt_id} {kva} kVA 11/0.433 kV"


def _select_consumers(rng, data_feeder_idx, data_dt_idx, topo: Topology, inj: Injection, n: int,
                      exclude: set[int]) -> list[int]:
    f_idx = topo.feeder_ids.index(inj.feeder)
    mask = data_feeder_idx == f_idx
    if inj.dt is not None:
        mask &= data_dt_idx == topo.dt_ids.index(inj.dt)
    cand = [i for i in np.flatnonzero(mask) if i not in exclude]
    n = min(n, len(cand))
    return sorted(int(i) for i in rng.choice(cand, size=n, replace=False)) if n else []


def generate(config: SimulationConfig) -> SimulationData:
    seed = config.seed
    topo = build_topology(TopologyConfig(config.n_feeders, config.dts_per_feeder, config.consumers_per_dt))
    hist_h, obs_h = HISTORY_DAYS * 24, OBSERVATION_DAYS * 24
    H, h0 = hist_h + obs_h, hist_h
    hours = np.arange(H)
    hod, day = hours % 24, hours // 24
    dow = day % 7  # absolute day 0 is a Monday (history length is a whole number of weeks)
    weekend_h = dow >= 5
    n_days = H // 24
    fids, dtids = topo.feeder_ids, topo.dt_ids
    n_f, n_dt = len(fids), len(dtids)

    # ---- consumers ----------------------------------------------------------------------
    rc = rng_for(seed, "consumers")
    ids, cats, dt_idx, f_idx, daily_kwh, shift = [], [], [], [], [], []
    for k, dtid in enumerate(dtids):
        dt = topo.dts[dtid]
        mix = P.CATEGORY_MIX[dt.archetype]
        for j in range(config.consumers_per_dt):
            cat = P.CATEGORIES[rc.choice(3, p=mix)]
            ids.append(f"C-{dtid}-{j + 1:03d}")
            cats.append(cat)
            dt_idx.append(k)
            f_idx.append(fids.index(dt.feeder))
            daily_kwh.append(P.DAILY_KWH_MEDIAN[cat] * float(np.exp(rc.normal(0, P.DAILY_KWH_SIGMA[cat]))))
            shift.append(int(rc.choice([-1, 0, 0, 0, 1])))
    C = len(ids)
    cats_a = np.array(cats)
    dt_idx_a, f_idx_a = np.array(dt_idx), np.array(f_idx)
    daily_kwh_a = np.array(daily_kwh)

    # Per-consumer hourly shapes [C, 2(weekday/weekend), 24] with persistent jitter.
    shapes = np.empty((C, 2, 24))
    jitter = np.exp(rc.normal(0, 0.08, size=(C, 24)))
    for i in range(C):
        for w in (0, 1):
            s = np.roll(P.shape(cats[i], bool(w)), shift[i]) * jitter[i]
            shapes[i, w] = s / s.mean()

    # ---- true demand --------------------------------------------------------------------
    rd = rng_for(seed, "demand")
    weather = np.zeros(n_days)
    for d in range(1, n_days):
        weather[d] = 0.7 * weather[d - 1] + rd.normal(0, 0.04)
    trend = 0.0015 * (np.arange(n_days) - HISTORY_DAYS)  # mild seasonal drift (pre-summer)
    day_factor = np.zeros((C, n_days))
    sig_d = np.array([P.DAILY_SIGMA[c] for c in cats])
    for d in range(1, n_days):
        day_factor[:, d] = 0.5 * day_factor[:, d - 1] + rd.normal(0, 1, C) * sig_d
    sens = np.array([P.WEATHER_SENSITIVITY[c] for c in cats])
    dowf = np.array([P.DOW_FACTOR[c] for c in cats])  # [C, 7]
    sig_h = np.array([P.HOURLY_SIGMA[c] for c in cats])
    hourly_noise = np.exp(rd.normal(0, 1, (C, H)) * sig_h[:, None] - 0.5 * sig_h[:, None] ** 2)
    true_kw = (
        (daily_kwh_a / 24.0)[:, None]
        * dowf[:, dow]
        * shapes[:, weekend_h.astype(int), hod]
        * np.exp(day_factor[:, day])
        * (1.0 + sens[:, None] * (weather[day] + trend[day])[None, :])
        * hourly_noise
    )

    # ---- DT sizing (planning assumption: DTs sized for their expected peak) ----------
    for k, dtid in enumerate(dtids):
        m = dt_idx_a == k
        pf = np.array([P.POWER_FACTOR[c] for c in cats_a[m]])
        peak_kva = np.percentile((true_kw[m] / pf[:, None]).sum(axis=0), 99.5)
        _apply_dt_rating(topo, dtid, _choose_dt_rating(peak_kva))

    # ---- benign genuine consumption drops (observation window only) -------------------
    rb = rng_for(seed, "benign")
    label_benign = np.zeros((C, H), dtype=bool)
    benign_events = []
    for i in np.flatnonzero(rb.random(C) < config.benign_change_rate):
        start = h0 + int(rb.integers(0, OBSERVATION_DAYS - 2)) * 24 + int(rb.integers(0, 24))
        end = min(H, start + int(rb.integers(2, 11)) * 24)
        factor = float(rb.uniform(0.2, 0.6))
        true_kw[i, start:end] *= factor
        label_benign[i, start:end] = True
        benign_events.append({"consumer": ids[i], "start_hour": start, "end_hour": end, "factor": factor,
                              "kind": "genuine consumption drop (e.g. vacancy or reduced operation)"})

    # ---- supply outages ---------------------------------------------------------------
    ro = rng_for(seed, "outages")
    energised = np.ones((n_f, H), dtype=bool)
    outages = []
    for f in range(n_f):
        for _ in range(int(ro.poisson(config.outage_rate * H / 168.0))):
            s = int(ro.integers(0, H - 4))
            e = s + int(ro.integers(1, 5))
            energised[f, s:e] = False
            outages.append({"feeder": fids[f], "start_hour": s, "end_hour": e})
    off_c = ~energised[f_idx_a]
    true_kw[off_c] = 0.0

    # ---- injections -----------------------------------------------------------------
    recorded_kw = true_kw.copy()
    unmetered_kw = np.zeros((n_dt, H))
    label_theft = np.zeros((C, H), dtype=bool)
    label_fault = np.zeros((C, H), dtype=bool)
    loss_factor = np.ones((n_f, H))
    noise_mult = np.full((n_f, H), config.noise_level)
    delay_override: list[tuple[int, np.ndarray, np.ndarray]] = []
    events: list[ResolvedEvent] = []
    used: set[int] = set()
    for n, inj in enumerate(config.injections):
        ri = rng_for(seed, "injection", n, inj.type)
        s = h0 + int(round(inj.onset_day * 24))
        e = min(H, s + int(round(inj.duration_days * 24)))
        fi = fids.index(inj.feeder)
        ev = ResolvedEvent(index=n, type=inj.type, theft_like=inj.type in THEFT_LIKE, feeder=inj.feeder,
                           dt=inj.dt, consumers=[], magnitude=inj.magnitude, start_hour=s, end_hour=e)
        if inj.type in ("sudden_deviation", "persistent_anomaly"):
            targets = _select_consumers(ri, f_idx_a, dt_idx_a, topo, inj, inj.n_consumers, used)
            used.update(targets)
            m = inj.magnitude / 100.0
            for i in targets:
                if inj.type == "sudden_deviation":
                    recorded_kw[i, s:e] = true_kw[i, s:e] * (1.0 - m)
                else:
                    ramp = np.clip((np.arange(s, e) - s) / 72.0, 0.0, 1.0)
                    sh = shapes[i, weekend_h[s:e].astype(int), hod[s:e]]
                    peak = sh >= np.median(shapes[i, 0])
                    w = np.where(peak, 1.0, 0.35)
                    recorded_kw[i, s:e] = true_kw[i, s:e] * (1.0 - m * ramp * w)
                label_theft[i, s:e] = True
            ev.consumers = [ids[i] for i in targets]
            ev.detail = {"consumer_daily_kwh": {ids[i]: round(float(daily_kwh_a[i]), 2) for i in targets}}
        elif inj.type == "unmetered_load":
            dt_id = inj.dt or dtids[[k for k, d in enumerate(dtids) if topo.dts[d].feeder == inj.feeder][
                int(ri.integers(0, config.dts_per_feeder))]]
            k = dtids.index(dt_id)
            avg_dt_kw = float(true_kw[dt_idx_a == k, :h0].sum(axis=0).mean())
            peak_kw = inj.magnitude / 100.0 * avg_dt_kw
            prof = P.unmetered_shape()[hod[s:e]]
            unmetered_kw[k, s:e] = peak_kw * prof * energised[fi, s:e]
            ev.dt = dt_id
            ev.detail = {"peak_kw": round(peak_kw, 2), "dt_average_load_kw": round(avg_dt_kw, 2),
                         "mean_kw": round(float(unmetered_kw[k, s:e].mean()), 2)}
        elif inj.type == "missing_delayed":
            targets = _select_consumers(ri, f_idx_a, dt_idx_a, topo, inj, inj.n_consumers, set())
            frac = inj.magnitude / 100.0
            for i in targets:
                d = np.zeros(e - s)
                covered = np.zeros(e - s, dtype=bool)
                while covered.mean() < frac and (e - s) > 0:
                    bs = int(ri.integers(0, e - s))
                    bl = int(ri.integers(4, 13))
                    sl = slice(bs, min(e - s, bs + bl))
                    if ri.random() < 0.5:
                        d[sl] = np.inf
                    else:
                        d[sl] = float(ri.integers(6, 49))
                    covered[sl] = True
                delay_override.append((i, np.arange(s, e)[covered], d[covered]))
                label_fault[i, s:e] |= np.isin(np.arange(s, e), np.arange(s, e)[covered])
            ev.consumers = [ids[i] for i in targets]
        elif inj.type == "noise_stress":
            noise_mult[fi, s:e] *= inj.magnitude
        elif inj.type == "loss_estimate_error":
            loss_factor[fi, s:e] *= 1.0 + inj.magnitude / 100.0
        events.append(ev)

    # Background utility loss-model error per feeder (constant over the run).
    rl = rng_for(seed, "loss-model")
    loss_factor *= (1.0 + rl.normal(0, config.loss_model_error_sd, n_f))[:, None]
    loss_factor *= 1.0 + config.systematic_loss_error_pct / 100.0

    # ---- power flow per feeder ------------------------------------------------------
    pf_c = np.array([P.POWER_FACTOR[c] for c in cats])
    tan_c = np.tan(np.arccos(pf_c))
    tan_unm = np.tan(np.arccos(0.90))
    feeder_true = np.zeros((n_f, H))
    dt_true = np.zeros((n_dt, H))
    losses = {k: np.zeros((n_f, H)) for k in ("mv", "dt_cu", "dt_core", "lv")}
    lv_dt = np.zeros((n_dt, H))
    branch_loading: dict[str, np.ndarray] = {}
    bus_v: dict[str, np.ndarray] = {}
    for f, fid in enumerate(fids):
        solver = FeederSolver(topo, fid)
        ks = [dtids.index(d) for d in solver.dt_ids]
        p_grp = np.zeros((len(ks), H))
        q_grp = np.zeros((len(ks), H))
        for j, k in enumerate(ks):
            m = dt_idx_a == k
            p_grp[j] = (true_kw[m].sum(axis=0) + unmetered_kw[k]) / 1000.0
            q_grp[j] = ((true_kw[m] * tan_c[m, None]).sum(axis=0) + unmetered_kw[k] * tan_unm) / 1000.0
        res = solver.solve(p_grp, q_grp, energised=energised[f])
        feeder_true[f] = res.p_head_mw * 1000.0
        for j, k in enumerate(ks):
            dt_true[k] = res.p_dt_lv_mw[j] * 1000.0
        for bi, (bid, kind) in enumerate(zip(res.branch_ids, res.branch_kind)):
            key = {"mv": "mv", "dt": "dt_cu", "lv": "lv"}[kind]
            losses[key][f] += res.branch_loss_mw[bi] * 1000.0
            branch_loading[bid] = res.branch_loading_pct[bi]
            if kind == "lv":
                lv_dt[dtids.index(topo.branches[bid].dt)] = res.branch_loss_mw[bi] * 1000.0
        losses["dt_core"][f] = res.core_loss_mw.sum(axis=0) * 1000.0
        bus_v.update(res.v_pu)

    # ---- meters -----------------------------------------------------------------------
    rm = rng_for(seed, "meters")
    fe, de, ce = METER_ERROR["feeder_head"], METER_ERROR["dt"], METER_ERROR["consumer"]
    f_bias = rm.normal(0, fe["bias"], n_f)
    d_bias = rm.normal(0, de["bias"], n_dt)
    c_bias = rm.normal(0, ce["bias"], C)
    f_rand = rm.normal(0, fe["random"], (n_f, H))
    d_rand = rm.normal(0, de["random"], (n_dt, H))
    c_rand = rm.normal(0, ce["random"], (C, H))
    f_missing = rm.random((n_f, H)) < fe["missing"]
    d_missing = rm.random((n_dt, H)) < de["missing"]
    dt_f = np.array([fids.index(topo.dts[d].feeder) for d in dtids])
    feeder_meter = feeder_true * (1.0 + noise_mult * (f_bias[:, None] + f_rand))
    dt_meter = dt_true * (1.0 + noise_mult[dt_f] * (d_bias[:, None] + d_rand))
    feeder_meter = np.where(f_missing, np.nan, np.round(np.maximum(feeder_meter, 0.0), 2))
    dt_meter = np.where(d_missing, np.nan, np.round(np.maximum(dt_meter, 0.0), 2))
    c_reading = recorded_kw * (1.0 + noise_mult[f_idx_a] * (c_bias[:, None] + c_rand))
    c_reading = np.round(np.maximum(c_reading, 0.0), 3)

    # ---- communication: delays, losses, duplicates ------------------------------------
    rcm = rng_for(seed, "comms")
    u = rcm.random((C, H))
    delay = np.zeros((C, H))
    delayed = u < config.base_delay_rate
    delay[delayed] = rcm.integers(2, 25, size=int(delayed.sum()))
    delay[(u >= config.base_delay_rate) & (u < config.base_delay_rate + config.base_missing_rate)] = np.inf
    # Meters on a de-energised feeder report after supply is restored.
    for o in outages:
        f = fids.index(o["feeder"])
        for h in range(o["start_hour"], o["end_hour"]):
            m = f_idx_a == f
            delay[m, h] = np.maximum(delay[m, h], o["end_hour"] - h)
    for i, hs, ds in delay_override:
        delay[i, hs] = ds
    ingestion = _ingest(c_reading, delay, config.duplicate_rate, rng_for(seed, "duplicates"))
    meter_kwh = ingestion.pop("values")

    data = SimulationData(
        config=config, topo=topo, H=H, h0=h0, hod=hod, dow=dow,
        consumer_ids=np.array(ids), consumer_category=cats_a, consumer_dt_idx=dt_idx_a,
        consumer_feeder_idx=f_idx_a, true_kwh=true_kw, recorded_kwh=recorded_kw, meter_kwh=meter_kwh,
        arrival_delay=delay, unmetered_kw=unmetered_kw, energised=energised,
        feeder_true_kwh=feeder_true, feeder_meter_kwh=feeder_meter, dt_true_kwh=dt_true, dt_meter_kwh=dt_meter,
        true_loss_kwh={**losses, "lv_dt": lv_dt}, loss_estimate_factor=loss_factor, noise_mult=noise_mult,
        label_theft_consumer=label_theft, label_benign_change=label_benign, label_data_fault=label_fault,
        label_unmetered_dt=unmetered_kw > 0, events=events, benign_events=benign_events, outages=outages,
        ingestion=ingestion, branch_loading_pct=branch_loading, bus_v_pu=bus_v,
    )
    data.data_hash = dataset_hash(data)
    return data


def _ingest(values: np.ndarray, delay: np.ndarray, dup_rate: float, rng: np.random.Generator) -> dict:
    """Simulate the head-end record stream and de-duplicate it.

    Every received reading becomes a record (consumer, interval, value, arrival). A share
    of records is re-transmitted (duplicates arrive later with the same key). Ingestion
    keeps the earliest record per (consumer, interval), so duplicates are never counted twice.
    """
    C, H = values.shape
    ok = np.isfinite(delay)
    ci, hi = np.nonzero(ok)
    arrival = hi + delay[ci, hi]
    vals = values[ci, hi]
    n_dup = int(round(dup_rate * len(ci)))
    dup = rng.choice(len(ci), size=n_dup, replace=False) if n_dup else np.array([], dtype=int)
    rec_c = np.concatenate([ci, ci[dup]])
    rec_h = np.concatenate([hi, hi[dup]])
    rec_v = np.concatenate([vals, vals[dup]])
    rec_a = np.concatenate([arrival, arrival[dup] + rng.integers(1, 4, size=n_dup)])
    order = np.lexsort((rec_a, rec_h, rec_c))
    key = rec_c[order] * H + rec_h[order]
    first = np.ones(len(key), dtype=bool)
    first[1:] = key[1:] != key[:-1]
    keep = order[first]
    out = np.full((C, H), np.nan)
    out[rec_c[keep], rec_h[keep]] = rec_v[keep]
    return {
        "values": out,
        "records_received": int(len(rec_c)),
        "duplicates_removed": int(len(rec_c) - first.sum()),
        "intervals_expected": int(C * H),
        "intervals_never_received": int((~ok).sum()),
        "intervals_delayed_over_1h": int((np.isfinite(delay) & (delay > 1)).sum()),
    }


def dataset_hash(d: SimulationData) -> str:
    h = hashlib.sha256()
    for arr in (d.meter_kwh, d.feeder_meter_kwh, d.dt_meter_kwh, d.true_kwh, d.unmetered_kw):
        h.update(np.nan_to_num(np.round(arr, 6), nan=-1.0).tobytes())
    h.update(d.arrival_delay.tobytes())
    return h.hexdigest()
