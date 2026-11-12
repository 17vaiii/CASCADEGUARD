# OWNER: P4 | NEEDS: P1,P2 | STATUS: ACTIVE
"""P4-side synthetic distribution layer with injected theft and look-alike negatives.

Why this exists: P2's ``meter_generator`` does not keep each consumer's *true* demand, so a
feeder-head meter (needed for the T2 energy balance) cannot be derived from it. This module
builds an explicit layer under the P1 corridor substations::

    corridor substation -> 11 kV feeder -> distribution transformer (DT) -> consumers

and simulates, per metering interval:

* legitimate demand by consumer type (daily/weekly shapes, summer trend, shared weather,
  holidays), plus look-alike legitimate changes (rooftop solar, new appliance, vacancy);
* five injected theft types using P2's class names (``meter_bypass``, ``meter_stop``,
  ``night_tapping``, ``hooking``, ``temporary_tampering``); diverted energy never appears on a
  consumer meter and unmetered (hidden) load is kept separate;
* physical losses from the T1 power-flow-fitted curves, giving DT and feeder-head meter readings
  with meter noise;
* tamper event logs (T7), including spurious alarms.

Labels are simulation ground truth for research only. IDs are synthetic pseudonyms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cascadeguard.theft import LOOKALIKE_TYPES, THEFT_TYPES, load_config
from cascadeguard.theft.technical_loss import (
    FeederSpec, LossCurve, fit_feeder_loss_curves, true_feeder_losses,
)

TYPE_MIX = {  # residential, commercial, small_industrial share by area (assumed)
    "urban": (0.72, 0.22, 0.06),
    "peri_urban": (0.78, 0.14, 0.08),
    "rural": (0.88, 0.08, 0.04),
}
CONSUMER_TYPES = ("residential", "commercial", "small_industrial")
TYPICAL_KW = {"residential": 0.9, "commercial": 4.5, "small_industrial": 12.0}
TAMPER_EVENTS = {
    "meter_bypass": ("cover_open", "magnetic_interference"),
    "meter_stop": ("power_off", "cover_open"),
    "temporary_tampering": ("magnetic_interference", "reverse_current", "cover_open"),
    "night_tapping": ("cover_open",),
    "hooking": ("cover_open",),
}
ALL_TAMPER_EVENTS = ("cover_open", "magnetic_interference", "reverse_current", "power_off")


@dataclass
class DistributionDataset:
    """Container for one simulated distribution dataset (arrays are [entity, time])."""

    timestamps: pd.DatetimeIndex
    history_end: int
    interval_hours: float
    feeders: pd.DataFrame
    dts: pd.DataFrame
    consumers: pd.DataFrame
    metered_kwh: np.ndarray
    true_kwh: np.ndarray
    dt_input_kwh: np.ndarray           # measured; NaN rows for unmetered DTs
    feeder_input_kwh: np.ndarray       # measured
    true_dt_loss_kwh: np.ndarray
    true_trunk_loss_kwh: np.ndarray
    tamper_log: pd.DataFrame
    specs: dict[str, FeederSpec] = field(default_factory=dict)
    curves: dict[str, dict[str, Any]] = field(default_factory=dict)
    seed: int = 42

    # -- convenience -------------------------------------------------------
    @property
    def n_periods(self) -> int:
        return len(self.timestamps)

    @property
    def ntl_kwh(self) -> np.ndarray:
        """True non-technical loss per consumer and interval (true draw minus metered).

        Intervals with a missing read (communication gap) count as zero NTL.
        """
        gap = np.isnan(self.metered_kwh)
        return np.where(gap, 0.0, np.maximum(0.0, self.true_kwh - np.nan_to_num(self.metered_kwh)))

    def metered_imputed(self) -> np.ndarray:
        """Meter reads with missing intervals estimated from the consumer's own hour-of-day mean
        over the available history (the usual utility 'estimated read' practice)."""
        met = self.metered_kwh.astype(np.float64)
        gap = np.isnan(met)
        if not gap.any():
            return met
        per_day = int(round(24 / self.interval_hours))
        n_hist = (self.history_end // per_day) * per_day
        hist = met[:, :n_hist].reshape(met.shape[0], -1, per_day)
        profile = np.nanmean(hist, axis=1)                      # [C, per_day]
        profile = np.where(np.isnan(profile), np.nanmean(met, axis=1, keepdims=True), profile)
        fill = np.tile(profile, (1, met.shape[1] // per_day + 1))[:, :met.shape[1]]
        return np.where(gap, fill, met)

    def consumer_index(self) -> dict[str, int]:
        return {cid: i for i, cid in enumerate(self.consumers.consumer_id)}

    # -- persistence -------------------------------------------------------
    def save(self, directory: str | Path) -> Path:
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            out / "arrays.npz", metered_kwh=self.metered_kwh, true_kwh=self.true_kwh,
            dt_input_kwh=self.dt_input_kwh, feeder_input_kwh=self.feeder_input_kwh,
            true_dt_loss_kwh=self.true_dt_loss_kwh, true_trunk_loss_kwh=self.true_trunk_loss_kwh,
            timestamps=self.timestamps.asi8)
        self.feeders.to_parquet(out / "feeders.parquet", index=False)
        self.dts.to_parquet(out / "dts.parquet", index=False)
        self.consumers.to_parquet(out / "consumers.parquet", index=False)
        self.tamper_log.to_parquet(out / "tamper_log.parquet", index=False)
        meta = {
            "history_end": self.history_end, "interval_hours": self.interval_hours, "seed": self.seed,
            "specs": {k: vars(v) for k, v in self.specs.items()},
            "curves": {k: {"feeder": v["feeder"].as_dict(), "dt": [c.as_dict() for c in v["dt"]],
                           "trunk_factor": v.get("trunk_factor", 1.0)} for k, v in self.curves.items()},
        }
        (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return out

    @classmethod
    def load(cls, directory: str | Path) -> "DistributionDataset":
        src = Path(directory)
        arrays = np.load(src / "arrays.npz")
        meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
        specs = {k: FeederSpec(**v) for k, v in meta["specs"].items()}
        curves = {k: {"feeder": LossCurve(**v["feeder"]), "dt": [LossCurve(**c) for c in v["dt"]],
                      "trunk_factor": v.get("trunk_factor", 1.0)} for k, v in meta["curves"].items()}
        return cls(
            timestamps=pd.DatetimeIndex(pd.to_datetime(arrays["timestamps"], utc=True)),
            history_end=int(meta["history_end"]), interval_hours=float(meta["interval_hours"]),
            feeders=pd.read_parquet(src / "feeders.parquet"), dts=pd.read_parquet(src / "dts.parquet"),
            consumers=pd.read_parquet(src / "consumers.parquet"),
            metered_kwh=arrays["metered_kwh"], true_kwh=arrays["true_kwh"],
            dt_input_kwh=arrays["dt_input_kwh"], feeder_input_kwh=arrays["feeder_input_kwh"],
            true_dt_loss_kwh=arrays["true_dt_loss_kwh"], true_trunk_loss_kwh=arrays["true_trunk_loss_kwh"],
            tamper_log=pd.read_parquet(src / "tamper_log.parquet"), specs=specs, curves=curves,
            seed=int(meta["seed"]))

    def to_meter_frame(self, consumer_ids: list[str] | None = None) -> pd.DataFrame:
        """Long-format rows following ``contracts/meter_data.schema.json`` (P2 contract)."""
        cons = self.consumers if consumer_ids is None else \
            self.consumers[self.consumers.consumer_id.isin(consumer_ids)]
        frames = []
        tamper = set(zip(self.tamper_log.consumer_id, self.tamper_log.t_idx))
        hidden = self.ntl_kwh
        reads = self.metered_imputed()
        for row in cons.itertuples(index=False):
            i = int(row.row)
            active = np.zeros(self.n_periods, dtype=bool)
            if row.event_start >= 0:
                active[row.event_start:row.event_end] = True
            unmetered = hidden[i] if row.theft_type in ("hooking", "night_tapping") else np.zeros(self.n_periods)
            frames.append(pd.DataFrame({
                "timestamp": self.timestamps, "consumer_id": row.consumer_id, "feeder_id": row.feeder_id,
                "consumer_type": row.consumer_type, "metered_kwh": np.round(reads[i], 5),
                "feeder_unmetered_kwh": np.round(unmetered, 5), "is_event": active,
                "is_suspected_loss": active & (hidden[i] > 1e-9), "theft_type": row.theft_type,
                "event_start": self.timestamps[row.event_start] if row.event_start >= 0 else pd.NaT,
                "event_end": self.timestamps[row.event_end - 1] if row.event_start >= 0 else pd.NaT,
                "tamper_event": [(row.consumer_id, t) in tamper for t in range(self.n_periods)],
                "scenario_seed": self.seed, "split": row.split,
            }))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Demand shapes
# ---------------------------------------------------------------------------

def _daily_shape(ctype: str, hour: np.ndarray, dow: np.ndarray) -> np.ndarray:
    if ctype == "residential":
        s = 0.45 + 0.35 * np.exp(-((hour - 7.5) / 1.8) ** 2) + 0.9 * np.exp(-((hour - 20.5) / 2.5) ** 2)
        wk = np.where(dow >= 5, 1.08, 1.0)
    elif ctype == "commercial":
        s = 0.25 + 1.0 * np.exp(-((hour - 14.0) / 4.0) ** 2)
        wk = np.where(dow == 6, 0.55, np.where(dow == 5, 0.8, 1.0))
    else:
        s = 0.6 + 0.5 * ((hour >= 8) & (hour < 20))
        wk = np.where(dow == 6, 0.5, 1.0)
    return s / s.mean() * wk


def _solar_shape(hour: np.ndarray) -> np.ndarray:
    return np.clip(np.exp(-((hour - 12.5) / 2.6) ** 2) - 0.05, 0.0, None)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def simulate_distribution(config: dict[str, Any] | None = None, seed: int | None = None,
                          scale: float = 1.0, injection: dict[str, Any] | None = None) -> DistributionDataset:
    """Simulate the distribution layer.

    ``scale`` multiplies the feeder count (for quick tests). ``injection`` optionally pins a
    synthetic demonstration theft to one generated feeder and controls its type, duration,
    intensity and number of affected consumers. The default research pipeline is unchanged.
    """
    cfg = config or load_config()
    sim = cfg["simulation"]
    seed = int(cfg.get("seed", 42) if seed is None else seed)
    rng = np.random.default_rng(seed)

    interval_min = int(sim["interval_minutes"])
    interval_h = interval_min / 60.0
    periods = int(sim["days"]) * 24 * 60 // interval_min
    per_day = 24 * 60 // interval_min
    timestamps = pd.date_range(sim["start"], periods=periods, freq=f"{interval_min}min", tz="UTC")
    history_end = int(sim["history_days"]) * per_day
    hour = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60.0
    dow = timestamps.dayofweek.to_numpy()
    day_idx = np.arange(periods) // per_day
    n_days = int(sim["days"])
    holiday_dates = {pd.Timestamp(d).date() for d in sim.get("holidays", [])}
    is_holiday = np.array([t.date() in holiday_dates for t in timestamps])

    # Corridor substation coordinates: km along the P1 corridor (x), 0 (y).
    from cascadeguard.grid.corridor_model import load_corridor_config
    sub_km = {b["id"]: float(b["km"]) for b in load_corridor_config()["buses"]}
    elec = cfg["feeder_electrical"]

    feeder_rows, dt_rows, cons_rows = [], [], []
    for sub, n_feed in sim["feeders_per_substation"].items():
        n_feed = max(1, int(round(n_feed * scale)))
        area = sim["area_by_substation"][sub]
        if injection and sub == injection.get("substation"):
            feeder_ids = [str(injection["feeder_id"])]
        else:
            feeder_ids = [f"{sub}_F{f:02d}" for f in range(n_feed)]
        for fid in feeder_ids:
            angle = rng.uniform(0, 2 * np.pi)
            n_dt = int(rng.integers(sim["dts_per_feeder"][0], sim["dts_per_feeder"][1] + 1))
            seg = rng.uniform(*elec["segment_km"], size=n_dt)
            dist = np.cumsum(seg)
            feeder_rows.append({"feeder_id": fid, "substation": sub, "area": area,
                                "x_km": sub_km[sub], "y_km": 0.0, "n_dts": n_dt})
            for d in range(n_dt):
                did = f"{fid}_DT{d}"
                dx, dy = sub_km[sub] + dist[d] * np.cos(angle), dist[d] * np.sin(angle)
                dt_rows.append({"dt_id": did, "feeder_id": fid, "substation": sub, "position": d,
                                "segment_km": float(seg[d]), "x_km": dx, "y_km": dy,
                                "metered": bool(rng.random() < sim["dt_metered_fraction"])})
                n_c = int(rng.integers(sim["consumers_per_dt"][0], sim["consumers_per_dt"][1] + 1))
                types = rng.choice(CONSUMER_TYPES, size=n_c, p=TYPE_MIX[area])
                for ctype in types:
                    kw = TYPICAL_KW[ctype] * (0.7 if (area == "rural" and ctype == "residential") else 1.0)
                    cons_rows.append({
                        "feeder_id": fid, "dt_id": did, "substation": sub, "area": area,
                        "consumer_type": str(ctype), "typical_kw": kw * float(rng.lognormal(0, 0.35)),
                        "x_km": dx + rng.normal(0, 0.15), "y_km": dy + rng.normal(0, 0.15),
                    })

    feeders = pd.DataFrame(feeder_rows)
    dts = pd.DataFrame(dt_rows)
    consumers = pd.DataFrame(cons_rows)
    n_c = len(consumers)
    consumers.insert(0, "consumer_id", [f"C{i + 1:07d}" for i in range(n_c)])
    consumers["row"] = np.arange(n_c)

    # --- legitimate demand ----------------------------------------------------
    shapes = {c: _daily_shape(c, hour, dow) for c in CONSUMER_TYPES}
    trend = 1.0 + 0.15 * day_idx / max(n_days - 1, 1)                     # rising summer AC load
    area_weather = {a: np.repeat(rng.lognormal(0, 0.05, n_days), per_day)[:periods] for a in TYPE_MIX}
    holiday_factor = {"residential": 1.1, "commercial": 0.5, "small_industrial": 0.4}
    base = np.empty((n_c, periods), dtype=np.float64)
    for row in consumers.itertuples(index=False):
        ct = row.consumer_type
        sigma = 0.18 if ct == "residential" else 0.10
        daily = np.repeat(rng.lognormal(0, 0.08, n_days), per_day)[:periods]
        noise = rng.lognormal(-0.5 * sigma**2, sigma, periods)
        hol = np.where(is_holiday, holiday_factor[ct], 1.0)
        wthr = area_weather[row.area] if ct != "small_industrial" else 1.0
        base[row.row] = row.typical_kw * shapes[ct] * trend * wthr * hol * daily * noise * interval_h

    consumers["theft_type"] = "none"
    consumers["event_start"] = -1
    consumers["event_end"] = -1
    consumers["lookalike_type"] = "none"
    consumers["lookalike_start"] = -1

    # --- who steals: spatially clustered on hotspot feeders ---------------------
    n_theft = int(round(n_c * sim["theft_fraction"]))
    n_look = int(round(n_c * sim["lookalike_fraction"]))
    feeder_ids = feeders.feeder_id.to_numpy()
    n_hot = max(1, int(round(len(feeder_ids) * sim.get("hotspot_feeder_fraction", 1.0))))
    hotspots = set(rng.choice(feeder_ids, size=n_hot, replace=False))
    feeders["hotspot"] = feeders.feeder_id.isin(hotspots)
    on_hot = consumers.feeder_id.isin(hotspots).to_numpy()
    share = float(sim.get("hotspot_theft_share", on_hot.mean()))
    weights = np.where(on_hot, share / max(on_hot.sum(), 1), (1 - share) / max((~on_hot).sum(), 1))
    if injection:
        feeder_id = str(injection["feeder_id"])
        eligible = consumers.index[consumers.feeder_id == feeder_id].to_numpy()
        if not len(eligible):
            raise ValueError(f"Unknown feeder for theft injection: {feeder_id}")
        n_theft = min(max(1, int(injection.get("affected_consumers", 1))), len(eligible))
        theft_rows = rng.choice(eligible, size=n_theft, replace=False)
    else:
        theft_rows = rng.choice(n_c, size=n_theft, replace=False, p=weights / weights.sum())
    rest = np.setdiff1d(np.arange(n_c), theft_rows)
    look_rows = rng.choice(rest, size=min(n_look, len(rest)), replace=False)

    # --- look-alike legitimate changes (hard negatives, P4-9) ----------------
    min_ev = int(sim["min_event_days"]) * per_day
    legit = base.copy()
    for k, r in enumerate(look_rows):
        kind = LOOKALIKE_TYPES[k % len(LOOKALIKE_TYPES)]
        start = int(rng.integers(history_end - 10 * per_day, periods - min_ev))
        consumers.loc[r, ["lookalike_type", "lookalike_start"]] = [kind, start]
        if kind == "rooftop_solar":
            cap = consumers.at[r, "typical_kw"] * rng.uniform(1.0, 2.5) * interval_h
            cloud = np.repeat(rng.uniform(0.5, 1.0, n_days), per_day)[:periods]
            gen = cap * _solar_shape(hour) * cloud
            legit[r, start:] = np.maximum(0.0, legit[r, start:] - gen[start:])
        elif kind == "new_appliance":
            legit[r, start:] *= rng.uniform(1.2, 1.6)
        else:  # vacancy
            end = min(periods, start + int(rng.integers(min_ev, 3 * min_ev)))
            legit[r, start:end] *= rng.uniform(0.1, 0.25)

    # --- theft injection ------------------------------------------------------
    metered = legit.copy()
    true = legit.copy()
    night_lo, night_hi = cfg["features"]["night_hours"]
    night = (hour >= night_lo) | (hour < night_hi + 1)
    for k, r in enumerate(theft_rows):
        kind = str(injection["theft_type"]) if injection else THEFT_TYPES[k % len(THEFT_TYPES)]
        if kind not in THEFT_TYPES:
            raise ValueError(f"Unsupported theft type: {kind}")
        if injection:
            start = max(history_end, int(injection.get("start_idx", history_end)))
            duration = max(min_ev, int(round(float(injection.get("duration_days", sim["min_event_days"])) * per_day)))
            end = min(periods, start + duration)
            if end - start < min_ev:
                raise ValueError("The injection must leave at least the configured minimum event duration")
        else:
            start = int(rng.integers(history_end, periods - min_ev))
            end = int(rng.integers(start + min_ev, periods + 1))
        consumers.loc[r, ["theft_type", "event_start", "event_end"]] = [kind, start, end]
        sl = slice(start, end)
        kw = consumers.at[r, "typical_kw"]
        intensity = float(injection.get("intensity", 1.0)) if injection else 1.0
        if kind == "meter_bypass":
            retained = rng.uniform(0.25, 0.65)
            metered[r, sl] = legit[r, sl] * np.clip(1.0 - (1.0 - retained) * intensity, 0.05, 0.95)
        elif kind == "meter_stop":
            metered[r, sl] = 0.0
        elif kind == "night_tapping":
            extra = kw * rng.uniform(0.8, 2.5) * interval_h * intensity
            mask = night[sl]
            true[r, sl] = legit[r, sl] + np.where(mask, extra, 0.0)
        elif kind == "hooking":
            extra = kw * rng.uniform(0.6, 2.0) * interval_h * intensity * rng.lognormal(0, 0.15, end - start)
            true[r, sl] = legit[r, sl] + extra
        else:  # temporary_tampering: tamper on ~half the days, intermittently
            days = np.unique(day_idx[sl])
            tamper_days = days[rng.random(len(days)) < 0.5]
            mask = np.isin(day_idx[sl], tamper_days)
            metered[r, sl] = np.where(mask, legit[r, sl] * rng.uniform(0.0, 0.35), legit[r, sl])

    consumers["true_ntl_kwh"] = np.maximum(0.0, true - metered).sum(axis=1)
    consumers["is_theft"] = consumers.theft_type != "none"

    # --- meter communication gaps (hard negative: zero/flat-looking reads) ---------
    consumers["comm_gap"] = False
    n_gap = int(round(n_c * sim.get("comm_failure_fraction", 0.0)))
    for r in rng.choice(n_c, size=n_gap, replace=False):
        start = int(rng.integers(per_day, periods - 2 * per_day))
        end = min(periods, start + int(rng.integers(2 * per_day, 10 * per_day)))
        metered[r, start:end] = np.nan
        consumers.at[r, "comm_gap"] = True

    # --- consumer-level split (stratified by theft type) ------------------------
    split = np.empty(n_c, dtype=object)
    for _, grp in consumers.groupby("theft_type"):
        idx = rng.permutation(grp.row.to_numpy())
        n_tr, n_va = int(round(0.70 * len(idx))), int(round(0.15 * len(idx)))
        split[idx[:n_tr]] = "train"
        split[idx[n_tr:n_tr + n_va]] = "validation"
        split[idx[n_tr + n_va:]] = "test"
    consumers["split"] = split

    # --- tamper event logs (T7) -------------------------------------------------
    tp = sim["tamper"]
    log_rows = []
    for row in consumers.itertuples(index=False):
        if row.theft_type != "none" and rng.random() < tp["thief_event_prob"].get(row.theft_type, 0.0):
            for t in rng.integers(row.event_start, row.event_end, size=int(rng.integers(1, 6))):
                log_rows.append((row.consumer_id, int(t), str(rng.choice(TAMPER_EVENTS[row.theft_type]))))
        n_spur = rng.poisson(tp["spurious_daily_rate"] * n_days)
        for t in rng.integers(0, periods, size=n_spur):
            log_rows.append((row.consumer_id, int(t), str(rng.choice(ALL_TAMPER_EVENTS))))
        if row.lookalike_type == "rooftop_solar" and rng.random() < 0.3:   # export trips reverse-current
            for t in rng.integers(row.lookalike_start, periods, size=int(rng.integers(1, 4))):
                log_rows.append((row.consumer_id, int(t), "reverse_current"))
    tamper_log = pd.DataFrame(log_rows, columns=["consumer_id", "t_idx", "event_type"])
    tamper_log["timestamp"] = timestamps[tamper_log.t_idx.to_numpy()] if len(tamper_log) else pd.Series(dtype="datetime64[ns, UTC]")
    tamper_log = tamper_log.sort_values(["consumer_id", "t_idx"]).reset_index(drop=True)

    # --- physics: DT / feeder energy with technical losses ------------------------
    dt_index = {d: i for i, d in enumerate(dts.dt_id)}
    cons_dt = consumers.dt_id.map(dt_index).to_numpy()
    dt_load_kwh = np.zeros((len(dts), periods))
    np.add.at(dt_load_kwh, cons_dt, true)
    hist_mean_kwh = np.zeros(len(dts))
    np.add.at(hist_mean_kwh, cons_dt, legit[:, :history_end].mean(axis=1))

    # Legitimate but unbilled loads that the energy balance also sees (not theft):
    # streetlights all period (constant night load) and late-billed new connections.
    dts["unbilled_kind"] = "none"
    feeders["new_connection"] = False
    feeder_energy = {f: hist_mean_kwh[dts.feeder_id.to_numpy() == f].sum() for f in feeders.feeder_id}
    night_mask = (hour >= 18.5) | (hour < 6)
    for f in feeders.feeder_id:
        rows = dts.index[dts.feeder_id == f].to_numpy()
        lo, hi = sim.get("streetlight_share", [0.0, 0.0])
        sl_kwh = feeder_energy[f] * rng.uniform(lo, hi) * per_day / night_mask[:per_day].sum()
        r = int(rng.choice(rows))
        dt_load_kwh[r] += np.where(night_mask, sl_kwh, 0.0)
        dts.at[r, "unbilled_kind"] = "streetlight"
        if rng.random() < sim.get("new_connection_feeder_fraction", 0.0):
            lo, hi = sim["new_connection_share"]
            start = int(rng.integers(history_end, periods - min_ev))
            r2 = int(rng.choice(rows))
            prof = _daily_shape("residential", hour, dow)
            dt_load_kwh[r2, start:] += feeder_energy[f] * rng.uniform(lo, hi) * prof[start:]
            dts.at[r2, "unbilled_kind"] = "new_connection"
            feeders.loc[feeders.feeder_id == f, "new_connection"] = True

    specs, curves = {}, {}
    true_dt_loss = np.zeros_like(dt_load_kwh)
    true_trunk = np.zeros((len(feeders), periods))
    noise = sim["meter_noise_pct"]
    feeder_input = np.zeros((len(feeders), periods))
    for fi, frow in enumerate(feeders.itertuples(index=False)):
        rows = dts.index[dts.feeder_id == frow.feeder_id].to_numpy()
        nominal_kw = hist_mean_kwh[rows] / interval_h
        peak_kva = 2.2 * nominal_kw / elec["power_factor"]
        ratings = [next((r for r in elec["dt_ratings_kva"] if r >= p), elec["dt_ratings_kva"][-1])
                   for p in peak_kva]
        spec = FeederSpec.from_config(frow.feeder_id, dts.segment_km[rows].tolist(), ratings,
                                      dts.dt_id[rows].tolist(), cfg)
        fit = fit_feeder_loss_curves(spec, nominal_kw, elec["fit_scales"])
        trunk_kw, dt_loss_kw = true_feeder_losses(spec, fit, dt_load_kwh[rows] / interval_h)
        true_dt_loss[rows] = dt_loss_kw * interval_h
        true_trunk[fi] = trunk_kw * interval_h
        feeder_input[fi] = dt_load_kwh[rows].sum(axis=0) + true_dt_loss[rows].sum(axis=0) + true_trunk[fi]
        specs[frow.feeder_id], curves[frow.feeder_id] = spec, fit
        dts.loc[rows, "rating_kva"] = ratings
    feeders["loss_a"] = [curves[f]["feeder"].a for f in feeders.feeder_id]
    feeders["loss_b"] = [curves[f]["feeder"].b for f in feeders.feeder_id]
    feeders["loss_c"] = [curves[f]["feeder"].c for f in feeders.feeder_id]

    bias = sim.get("meter_bias_pct", {"feeder": 0.0, "dt": 0.0})
    drift_w = float(sim.get("meter_drift_pct_per_week", 0.0)) / 100.0
    week = np.arange(periods) // (7 * per_day)

    def meter_error(n: int, level: str) -> np.ndarray:
        b = rng.normal(0, bias[level] / 100.0, (n, 1))
        walk = np.cumsum(rng.normal(0, drift_w, (n, week.max() + 1)), axis=1)[:, week]
        return 1.0 + b + walk + rng.normal(0, noise[level] / 100.0, (n, periods))

    feeder_meas = feeder_input * meter_error(len(feeders), "feeder")
    dt_true_input = dt_load_kwh + true_dt_loss
    dt_meas = dt_true_input * meter_error(len(dts), "dt")
    dt_meas[~dts.metered.to_numpy()] = np.nan

    return DistributionDataset(
        timestamps=timestamps, history_end=history_end, interval_hours=interval_h,
        feeders=feeders, dts=dts, consumers=consumers.drop(columns=[]),
        metered_kwh=metered.astype(np.float32), true_kwh=true.astype(np.float32),
        dt_input_kwh=dt_meas.astype(np.float32), feeder_input_kwh=feeder_meas.astype(np.float32),
        true_dt_loss_kwh=true_dt_loss.astype(np.float32), true_trunk_loss_kwh=true_trunk.astype(np.float32),
        tamper_log=tamper_log, specs=specs, curves=curves, seed=seed)
