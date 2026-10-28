"""Live simulation runs served by the API.

A SimulationRun owns one generated dataset and everything derived from it. State for
any timeline step is either cached or recomputed deterministically, so moving backward
in time always shows the correct state. A background thread precomputes the hourly
detection-score timeline; any step requested before it finishes is computed on demand
through the same functions.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .config import SYNTHETIC_START
from .detection.bundle import ModelBundle
from .detection.methods import CONSUMER_METHODS, UNIT_METHODS
from .explanations.explain import PRIORITY_WEIGHT, explain_consumer, explain_unit
from .features.build import RuleConfig
from .pipeline import RunContext, prepare
from .simulation import profiles as P
from .simulation.grid_snapshot import HAVE_PANDAPOWER, GridSnapshotModel
from .simulation.scenarios import SimulationConfig

log = logging.getLogger("gridwatch.engine")

DEFAULT_CONSUMER_METHOD = "rf_combined"
DEFAULT_UNIT_METHOD = "rf_unit_combined"
WARNING_FRACTION = 0.75  # "warning" overlay when score >= 75 % of the decision threshold


class LRU(OrderedDict):
    def __init__(self, maxsize: int):
        super().__init__()
        self.maxsize = maxsize

    def get_or(self, key, fn):
        if key in self:
            self.move_to_end(key)
            return self[key]
        val = fn()
        self[key] = val
        if len(self) > self.maxsize:
            self.popitem(last=False)
        return val


class SimulationRun:
    def __init__(self, config: SimulationConfig, bundle: ModelBundle, run_id: str | None = None,
                 rules: RuleConfig | None = None):
        t0 = time.perf_counter()
        self.id = run_id or uuid.uuid4().hex[:12]
        self.config = config
        self.rules = rules or RuleConfig()
        self.bundle = bundle
        self.ctx: RunContext = prepare(config, self.rules)
        self.d = self.ctx.data
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.generation_ms = (time.perf_counter() - t0) * 1000.0
        self._eval_cache = LRU(24)
        self._feat_cache = LRU(48)
        self._feat_lock = threading.Lock()
        self._pf_cache = LRU(64)
        self._pf_lock = threading.Lock()
        self._eval_lock = threading.Lock()
        self._pf_model = GridSnapshotModel(self.d.topo) if HAVE_PANDAPOWER else None
        n = self.d.n_steps
        C, n_dt, n_f = len(self.d.consumer_ids), len(self.d.dt_ids), len(self.d.feeder_ids)
        self.timeline = {
            "consumer": {m: np.full((C, n), np.nan, dtype=np.float32) for m in CONSUMER_METHODS},
            "dt": {m: np.full((n_dt, n), np.nan, dtype=np.float32) for m in UNIT_METHODS},
            "feeder": {m: np.full((n_f, n), np.nan, dtype=np.float32) for m in UNIT_METHODS},
            "balance": {k: {q: np.full((nu, n), np.nan, dtype=np.float32) for q in ("unexplained", "ratio", "z", "input")}
                        for k, nu in (("dt", n_dt), ("feeder", n_f))},
        }
        self.timeline_done = np.zeros(n, dtype=bool)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._precompute, name=f"timeline-{self.id}", daemon=True)
        self._thread.start()

    # ---- time helpers ------------------------------------------------------------------
    def tau(self, t: int) -> int:
        if not 0 <= t < self.d.n_steps:
            raise ValueError(f"step must be in [0, {self.d.n_steps - 1}]")
        return self.d.h0 + t

    def timestamp(self, t: int) -> str:
        return (datetime.fromisoformat(SYNTHETIC_START) + timedelta(hours=t)).isoformat(timespec="minutes")

    def step_of_hour(self, h: int) -> int:
        return int(h - self.d.h0)

    # ---- evaluation ----------------------------------------------------------------------
    def features_at(self, t: int) -> dict:
        tau = self.tau(t)
        with self._feat_lock:
            return self._feat_cache.get_or(t, lambda: self.ctx.features.at(tau))

    def evaluate(self, t: int) -> dict:
        """Features + scores of every method at step t (end of hour t). This executes the models."""
        def compute():
            tau = self.tau(t)
            t0 = time.perf_counter()
            ft = self.features_at(t)
            tables = self.ctx.features.tables(ft, run_id=self.id)
            cs = self.bundle.score_consumers(tables["consumer"])
            us = {k: self.bundle.score_units(k, tables[k], tables["consumer"], cs) for k in ("dt", "feeder")}
            return {"t": t, "tau": tau, "ft": ft, "tables": tables, "consumer_scores": cs, "unit_scores": us,
                    "compute_ms": (time.perf_counter() - t0) * 1000.0}
        with self._eval_lock:
            return self._eval_cache.get_or(t, compute)

    def _store_timeline(self, ts: list[int], fts: list[dict], tables: list[dict]) -> None:
        cons = pd.concat([tb["consumer"] for tb in tables], ignore_index=True)
        cs = self.bundle.score_consumers(cons)
        C = len(self.d.consumer_ids)
        for m in CONSUMER_METHODS:
            self.timeline["consumer"][m][:, ts] = cs[m].to_numpy().reshape(len(ts), C).T
        for kind in ("dt", "feeder"):
            u = pd.concat([tb[kind] for tb in tables], ignore_index=True)
            us = self.bundle.score_units(kind, u, cons, cs)
            nu = len(tables[0][kind])
            for m in UNIT_METHODS:
                self.timeline[kind][m][:, ts] = us[m].to_numpy().reshape(len(ts), nu).T
            for j, ft in zip(ts, fts):
                b = ft["units"][kind]["balance"][24]
                for q in ("unexplained", "ratio", "z", "input"):
                    self.timeline["balance"][kind][q][:, j] = b[q]
        self.timeline_done[ts] = True

    def _precompute(self) -> None:
        t0 = time.perf_counter()
        try:
            chunk = 24
            for s in range(0, self.d.n_steps, chunk):
                if self._stop.is_set():
                    return
                ts = [t for t in range(s, min(s + chunk, self.d.n_steps)) if not self.timeline_done[t]]
                if not ts:
                    continue
                fts = [self.ctx.features.at(self.tau(t)) for t in ts]
                tables = [self.ctx.features.tables(ft, run_id=self.id) for ft in fts]
                self._store_timeline(ts, fts, tables)
            log.info("run %s: score timeline precomputed in %.1f s", self.id, time.perf_counter() - t0)
        except Exception:  # pragma: no cover
            log.exception("timeline precomputation failed for run %s", self.id)

    def timeline_progress(self) -> float:
        return float(self.timeline_done.mean())

    def stop(self) -> None:
        self._stop.set()

    # ---- network state -----------------------------------------------------------------
    def power_flow(self, t: int) -> dict:
        h = self.tau(t)

        def compute():
            d = self.d
            if self._pf_model is None:
                return {"converged": False, "solver": "unavailable (pandapower not installed)"}
            tan = np.tan(np.arccos([P.POWER_FACTOR[c] for c in d.consumer_category]))
            p, q = {}, {}
            for k, dt in enumerate(d.dt_ids):
                m = d.consumer_dt_idx == k
                p[dt] = float(d.true_kwh[m, h].sum() + d.unmetered_kw[k, h]) / 1000.0
                q[dt] = float((d.true_kwh[m, h] * tan[m]).sum() + d.unmetered_kw[k, h] * np.tan(np.arccos(0.9))) / 1000.0
            energised = {f: bool(d.energised[i, h]) for i, f in enumerate(d.feeder_ids)}
            with self._pf_lock:
                return self._pf_model.solve(int(d.hod[h]), int(d.dow[h]), p, q, energised)
        return self._pf_cache.get_or(t, compute)

    def active_events(self, t: int) -> list[dict]:
        h = self.tau(t)
        out = []
        for ev in self.d.events:
            phase = "pending" if h < ev.start_hour else "active" if h < ev.end_hour else "ended"
            out.append({
                "index": ev.index, "type": ev.type, "theft_like": ev.theft_like, "feeder": ev.feeder, "dt": ev.dt,
                "consumers": ev.consumers, "magnitude": ev.magnitude, "phase": phase,
                "start_step": self.step_of_hour(ev.start_hour), "end_step": self.step_of_hour(ev.end_hour),
                "detail": ev.detail,
            })
        return out

    def _status(self, score: float, thr: float) -> str:
        if not np.isfinite(score):
            return "unknown"
        if score >= thr:
            return "alert"
        if score >= WARNING_FRACTION * thr:
            return "warning"
        return "normal"

    def state(self, t: int, consumer_method: str = DEFAULT_CONSUMER_METHOD,
              unit_method: str = DEFAULT_UNIT_METHOD) -> dict:
        d = self.d
        h = self.tau(t)
        t0 = time.perf_counter()
        if self.timeline_done[t]:  # scores already computed by the same models in the background
            ft = self.features_at(t)
            cscore = self.timeline["consumer"][consumer_method][:, t].astype(float)
            uscore = {k: self.timeline[k][unit_method][:, t].astype(float) for k in ("feeder", "dt")}
            source = "precomputed timeline"
        else:
            ev = self.evaluate(t)
            ft = ev["ft"]
            cscore = ev["consumer_scores"][consumer_method].to_numpy()
            uscore = {k: ev["unit_scores"][k][unit_method].to_numpy() for k in ("feeder", "dt")}
            source = "computed on request"
        pf = self.power_flow(t)
        cthr = self.bundle.threshold(consumer_method, "consumer")
        cflag = cscore >= cthr
        units = {}
        for kind, ids in (("feeder", d.feeder_ids), ("dt", d.dt_ids)):
            thr = self.bundle.threshold(unit_method, kind)
            sc = uscore[kind]
            b24 = ft["units"][kind]["balance"][24]
            rows = []
            for j, uid in enumerate(ids):
                members = (d.consumer_feeder_idx == j) if kind == "feeder" else (d.consumer_dt_idx == j)
                meter = d.feeder_meter_kwh[j, h] if kind == "feeder" else d.dt_meter_kwh[j, h]
                rows.append({
                    "id": uid, "score": float(sc[j]), "threshold": thr, "status": self._status(float(sc[j]), thr),
                    "balance_24h": {"input_kwh": float(b24["input"][j]), "metered_kwh": float(b24["metered"][j]),
                                    "imputed_kwh": float(b24["imputed"][j]), "loss_est_kwh": float(b24["loss_est"][j]),
                                    "unexplained_kwh": float(b24["unexplained"][j]), "ratio": float(b24["ratio"][j]),
                                    "z": float(b24["z"][j]), "coverage": float(b24["coverage"][j])},
                    "meter_kwh_this_hour": None if not np.isfinite(meter) else float(meter),
                    "consumers": int(members.sum()), "consumers_flagged": int((members & cflag).sum()),
                    "energised": bool(d.energised[j if kind == "feeder" else d.dt_feeder_idx()[j], h]),
                })
            units[kind] = rows
        groups = []
        for k, dt in enumerate(d.dt_ids):
            m = d.consumer_dt_idx == k
            avail = m & np.isfinite(d.meter_kwh[:, h]) & (d.arrival_delay[:, h] <= 0)
            groups.append({
                "dt": dt, "consumers": int(m.sum()),
                "metered_kwh_this_hour": float(np.nansum(np.where(avail, d.meter_kwh[:, h], 0.0))),
                "readings_received": int(avail.sum()),
                "truth": {"true_demand_kw": float(d.true_kwh[m, h].sum()), "unmetered_kw": float(d.unmetered_kw[k, h]),
                          "theft_like_consumers_active": int(d.label_theft_consumer[m, h].sum())},
            })
        events = self.active_events(t)
        phases = {e["phase"] for e in events}
        status = ("simulated event active" if "active" in phases else "simulated event scheduled, not started yet"
                  if "pending" in phases else "simulated event ended" if events else "no event injected")
        return {
            "run_id": self.id, "t": t, "n_steps": d.n_steps, "timestamp": self.timestamp(t),
            "hour_of_day": int(d.hod[h]), "day": t // 24, "weekday": int(d.dow[h]),
            "scenario": {"code": self.config.scenario, "label": self.config.label,
                         "status": status, "events": events},
            "power_flow": pf,
            "hydro_dispatch_mw": P.hydro_dispatch_mw(int(d.hod[h])),
            "units": units, "groups": groups,
            "methods": {"consumer": consumer_method, "unit": unit_method,
                        "consumer_threshold": cthr},
            "consumers_flagged": [str(x) for x in d.consumer_ids[cflag]],
            "timeline_progress": self.timeline_progress(),
            "scores_source": source,
            "evaluation_ms": round((time.perf_counter() - t0) * 1000.0, 1),
        }

    # ---- alerts ---------------------------------------------------------------------------
    def _score_display(self, method: str, score: float, level: str) -> str:
        if method.startswith("if_"):
            ref = method.replace("_max", "")
            pct = float(self.bundle.if_percentile(ref, np.array([score]))[0])
            return f"anomaly score {score:.3f} (higher than {pct:.1f}% of training windows)"
        if method.startswith("rf_"):
            return f"classifier score {score:.2f}"
        return f"rule score {score:.2f}"

    def alerts(self, t: int, consumer_method: str = DEFAULT_CONSUMER_METHOD,
               unit_method: str = DEFAULT_UNIT_METHOD, limit: int = 40) -> dict:
        if consumer_method not in CONSUMER_METHODS or unit_method not in UNIT_METHODS:
            raise ValueError("unknown method")
        t0 = time.perf_counter()
        ev = self.evaluate(t)
        ft = ev["ft"]
        cs = ev["consumer_scores"][consumer_method].to_numpy()
        cthr = self.bundle.threshold(consumer_method, "consumer")
        cflag = cs >= cthr
        out = []
        for i in np.flatnonzero(cflag):
            out.append(explain_consumer(self.ctx, ft, int(i), consumer_method, float(cs[i]), cthr, self.bundle,
                                        self._score_display(consumer_method, float(cs[i]), "consumer")))
        for kind in ("feeder", "dt"):
            us = ev["unit_scores"][kind][unit_method].to_numpy()
            thr = self.bundle.threshold(unit_method, kind)
            for j in np.flatnonzero(us >= thr):
                out.append(explain_unit(self.ctx, ft, kind, int(j), unit_method, float(us[j]), thr, self.bundle,
                                        self._score_display(unit_method, float(us[j]), kind), cflag))
        for a in out:
            a["priority_index"] = PRIORITY_WEIGHT[a["priority"]["level"]] * (
                1.0 + np.log1p(a["energy_at_stake_kwh_per_day"]))
            a["truth"] = self._truth_for(a, t)
        out.sort(key=lambda a: -a["priority_index"])
        return {"t": t, "timestamp": self.timestamp(t), "consumer_method": consumer_method, "unit_method": unit_method,
                "alerts": out[:limit], "n_alerts": len(out), "compute_ms": round((time.perf_counter() - t0) * 1000, 1),
                "note": "Screening output on synthetic data. Alerts prioritise authorised investigation; they are "
                        "not findings of theft."}

    def _truth_for(self, alert: dict, t: int) -> dict:
        """Simulation ground truth for an alert (only knowable because this is a simulation)."""
        d = self.d
        h = self.tau(t)
        s = slice(max(0, h - 23), h + 1)
        if alert["kind"] == "consumer":
            i = int(np.flatnonzero(d.consumer_ids == alert["id"])[0])
            return {"theft_like_active": bool(d.label_theft_consumer[i, s].any()),
                    "benign_change_active": bool(d.label_benign_change[i, s].any()),
                    "data_fault_active": bool(d.label_data_fault[i, s].any())}
        if alert["kind"] == "dt":
            k = d.dt_ids.index(alert["id"])
            return {"theft_like_active": bool(d.label_theft_dt()[k, s].any()),
                    "unmetered_load_active": bool(d.label_unmetered_dt[k, s].any())}
        f = d.feeder_ids.index(alert["id"])
        return {"theft_like_active": bool(d.label_theft_feeder()[f, s].any())}

    # ---- comparison -------------------------------------------------------------------------
    def compare(self, t: int) -> dict:
        """All methods on the same step vs. simulation ground truth, with disagreement analysis."""
        d = self.d
        ev = self.evaluate(t)
        ft = ev["ft"]
        lab = self.ctx.features.labels_at(self.tau(t))
        consumer_rows = []
        flags = {}
        for m, info in CONSUMER_METHODS.items():
            s = ev["consumer_scores"][m].to_numpy()
            thr = self.bundle.threshold(m, "consumer")
            fl = s >= thr
            flags[m] = fl
            pos = lab["consumer"] == 1
            neg = lab["consumer"] == 0
            consumer_rows.append({
                "method": m, "name": info["name"], "family": info["family"], "signals": info["signals"],
                "threshold": thr, "flagged": int(fl.sum()), "true_positives": int((fl & pos).sum()),
                "false_positives": int((fl & neg).sum()), "missed": int((~fl & pos).sum()),
                "flagged_benign_changes": int((fl & lab["consumer_benign"]).sum()),
                "flagged_data_faults": int((fl & lab["consumer_fault"]).sum()),
                "flagged_ids": [str(x) for x in d.consumer_ids[fl]][:30],
            })
        unit_rows = {}
        for kind, ids in (("feeder", d.feeder_ids), ("dt", d.dt_ids)):
            rows = []
            for m, info in UNIT_METHODS.items():
                s = ev["unit_scores"][kind][m].to_numpy()
                thr = self.bundle.threshold(m, kind)
                fl = s >= thr
                rows.append({"method": m, "name": info["name"], "family": info["family"], "threshold": thr,
                             "flagged_ids": [ids[j] for j in np.flatnonzero(fl)],
                             "truth_ids": [ids[j] for j in np.flatnonzero(lab[kind] == 1)],
                             "scores": {ids[j]: round(float(s[j]), 4) for j in range(len(ids))}})
            unit_rows[kind] = rows
        # Disagreements between the transparent consumer rule and the combined Random Forest.
        a, b = "consumer_rule", "rf_combined"
        dis = []
        raw = ft["consumer_raw"]
        dtz = ft["units"]["dt"]["balance"][72]["z"]
        for i in np.flatnonzero(flags[a] != flags[b])[:12]:
            k = d.consumer_dt_idx[i]
            who = a if flags[a][i] else b
            reason = (f"peer-adjusted 72 h ratio {raw['peer_ratio_72'][i]:.2f}; DT {d.dt_ids[k]} imbalance "
                      f"{dtz[k]:.1f} sigma over 72 h; {100 * ft['completeness_72'][i]:.0f}% readings received.")
            if flags[a][i] and dtz[k] < 1.0:
                reason += " The rule sees only the consumption drop; the combined model also sees that the DT " \
                          "balance does not corroborate it."
            elif flags[b][i] and not flags[a][i]:
                reason += " The combined model uses the DT imbalance and shape features; the drop is below the " \
                          "rule's fixed shortfall threshold."
            dis.append({"consumer": str(d.consumer_ids[i]), "flagged_by": who,
                        "truth": {"theft_like": bool(lab["consumer"][i] == 1), "benign_change": bool(lab["consumer_benign"][i]),
                                  "data_fault": bool(lab["consumer_fault"][i])}, "explanation": reason})
        return {"t": t, "timestamp": self.timestamp(t), "consumer_methods": consumer_rows, "unit_methods": unit_rows,
                "disagreements": {"between": [a, b], "items": dis},
                "note": "Ground truth is shown only because this is a simulation; a real deployment has no labels."}

    # ---- time series ------------------------------------------------------------------------
    def consumer_series(self, cid: str) -> dict:
        d = self.d
        idx = np.flatnonzero(d.consumer_ids == cid)
        if not len(idx):
            raise KeyError(cid)
        i = int(idx[0])
        h0, H = d.h0, d.H
        sl = slice(h0, H)
        meter = d.meter_kwh[i, sl]
        delay = d.arrival_delay[i, sl]
        steps = np.arange(d.n_steps)
        arrival = np.where(np.isfinite(delay), steps + delay, -1)
        base = self.ctx.baseline
        return {
            "id": cid, "category": str(d.consumer_category[i]), "feeder": d.feeder_ids[d.consumer_feeder_idx[i]],
            "dt": d.dt_ids[d.consumer_dt_idx[i]],
            "observed_kwh": [None if not np.isfinite(v) else round(float(v), 4) for v in meter],
            "arrival_step": [int(a) for a in arrival],
            "expected_kwh": [round(float(v), 4) for v in base.expected_kwh[i, sl]],
            "expected_sd": [round(float(v), 4) for v in base.expected_sd[i, sl]],
            "truth": {"true_kwh": [round(float(v), 4) for v in d.true_kwh[i, sl]],
                      "theft_like": d.label_theft_consumer[i, sl].astype(int).tolist(),
                      "benign_change": d.label_benign_change[i, sl].astype(int).tolist(),
                      "data_fault": d.label_data_fault[i, sl].astype(int).tolist()},
            "scores": {m: [None if not np.isfinite(v) else round(float(v), 4) for v in self.timeline["consumer"][m][i]]
                       for m in CONSUMER_METHODS},
            "thresholds": {m: self.bundle.threshold(m, "consumer") for m in CONSUMER_METHODS},
            "timeline_progress": self.timeline_progress(),
        }

    def unit_series(self, kind: str, uid: str, t: int) -> dict:
        d = self.d
        ids = d.feeder_ids if kind == "feeder" else d.dt_ids
        if uid not in ids:
            raise KeyError(uid)
        j = ids.index(uid)
        tau = self.tau(t)
        acc = self.ctx.accountant
        comp = acc.components(d.h0, tau + 1, tau)
        hr = acc.hourly(comp, kind)
        r = lambda arr: [None if not np.isfinite(v) else round(float(v), 3) for v in arr]  # noqa: E731
        bal = self.timeline["balance"][kind]
        truth_unm = (d.unmetered_kw[j, d.h0:tau + 1] if kind == "dt" else
                     d.unmetered_kw[d.dt_feeder_idx() == j, d.h0:tau + 1].sum(axis=0))
        true_input = (d.dt_true_kwh[j, d.h0:tau + 1] if kind == "dt" else d.feeder_true_kwh[j, d.h0:tau + 1])
        return {
            "kind": kind, "id": uid, "as_of_step": t,
            "hourly": {k: r(hr[k][j]) for k in ("input", "metered", "imputed", "loss_est", "unexplained")},
            "rolling_24h": {q: r(bal[q][j]) for q in ("unexplained", "ratio", "z", "input")},
            "scores": {m: r(self.timeline[kind][m][j]) for m in UNIT_METHODS},
            "thresholds": {m: self.bundle.threshold(m, kind) for m in UNIT_METHODS},
            "truth": {"unmetered_kw": r(truth_unm), "true_input_kwh": r(true_input),
                      "theft_like": (d.label_theft_dt()[j] if kind == "dt" else d.label_theft_feeder()[j])[
                          d.h0:tau + 1].astype(int).tolist()},
            "timeline_progress": self.timeline_progress(),
        }

    def consumers_table(self, t: int, feeder: str | None = None, dt: str | None = None,
                        method: str = DEFAULT_CONSUMER_METHOD) -> list[dict]:
        d = self.d
        ev = self.evaluate(t)
        raw = ev["ft"]["consumer_raw"]
        sc = ev["consumer_scores"][method].to_numpy()
        thr = self.bundle.threshold(method, "consumer")
        rows = []
        for i, cid in enumerate(d.consumer_ids):
            fid, did = d.feeder_ids[d.consumer_feeder_idx[i]], d.dt_ids[d.consumer_dt_idx[i]]
            if (feeder and fid != feeder) or (dt and did != dt):
                continue
            rows.append({"id": str(cid), "feeder": fid, "dt": did, "category": str(d.consumer_category[i]),
                         "ratio_72": round(float(raw["ratio_72"][i]), 3),
                         "peer_ratio_72": round(float(raw["peer_ratio_72"][i]), 3),
                         "completeness_72": round(float(ev["ft"]["completeness_72"][i]), 3),
                         "score": round(float(sc[i]), 4), "flagged": bool(sc[i] >= thr)})
        rows.sort(key=lambda r: -r["score"])
        return rows

    def summary(self) -> dict:
        d = self.d
        return {
            "id": self.id, "created_at": self.created_at, "config": self.config.model_dump(),
            "data_hash": d.data_hash, "n_consumers": int(len(d.consumer_ids)), "n_steps": d.n_steps,
            "n_feeders": len(d.feeder_ids), "n_dts": len(d.dt_ids), "start_timestamp": self.timestamp(0),
            "generation_ms": round(self.generation_ms, 1), "events": self.active_events(0),
            "benign_events": [{**e, "start_step": self.step_of_hour(e["start_hour"]),
                               "end_step": self.step_of_hour(e["end_hour"])} for e in d.benign_events],
            "outages": [{**o, "start_step": self.step_of_hour(o["start_hour"]),
                         "end_step": self.step_of_hour(o["end_hour"])} for o in d.outages],
            "ingestion": d.ingestion, "pandapower": HAVE_PANDAPOWER,
        }

    def topology(self) -> dict:
        return self.d.topo.to_api()
