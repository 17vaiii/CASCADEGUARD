"""Reproducible experiment suite.

    python -m gridwatch.experiments.run            # full suite (~10-15 min on a laptop)
    python -m gridwatch.experiments.run --quick    # smaller smoke version

Steps
  1. train models on TRAIN seeds, select thresholds on VALIDATION seeds (disjoint runs)
  2. main comparison on TEST seeds (consumer, DT and feeder level) with cluster-bootstrap CIs
  3. benign-confounder analysis (genuine drops, data faults)
  4. sweeps: anomaly prevalence, meter noise, missing data, technical-loss estimation error
  5. localisation (single-feeder theft runs), detection delay, energy-balance recovery
  6. runtime scaling
All numbers are computed here from saved predictions and written to
artifacts/results/results.json, docs/experiments/results.md and per-window CSVs.
Every number is a result on the documented *synthetic* benchmark only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
import sklearn

from ..config import PROJECT_DIR, RESULTS_DIR
from ..detection.bundle import ModelBundle, train_bundle
from ..detection.methods import CONSUMER_METHODS, UNIT_METHODS
from ..simulation.scenarios import Injection, SimulationConfig
from .benchmark import TEST_SEEDS, TRAIN_SEEDS, VAL_SEEDS, BenchmarkSpec, benchmark_config, describe_spec
from .metrics import evaluate, paired_difference

log = logging.getLogger("gridwatch.experiments")
WORKERS = max(1, min(8, (os.cpu_count() or 2) - 2))
SWEEP_METHODS_C = ["consumer_rule", "combined_rule", "if_consumer", "if_combined", "rf_consumer", "rf_combined"]
SWEEP_METHODS_U = ["balance_rule", "consumer_rule_max", "rf_consumer_max", "rf_unit_combined"]


# --------------------------------------------------------------------------- workers
def _frames_worker(args):
    seed, spec = args
    from ..pipeline import prepare

    ctx = prepare(benchmark_config(seed, spec))
    return ctx.features.frame(ctx.features.daily_taus(), run_id=str(seed))


def _frames(seeds: list[int], spec: BenchmarkSpec | None = None) -> dict[str, pd.DataFrame]:
    spec = spec or BenchmarkSpec()
    with ProcessPoolExecutor(WORKERS) as ex:
        parts = list(ex.map(_frames_worker, [(s, spec) for s in seeds]))
    return {k: pd.concat([p[k] for p in parts], ignore_index=True) for k in ("consumer", "dt", "feeder")}


def _delay_worker(args):
    seed, step = args
    from ..pipeline import prepare

    ctx = prepare(benchmark_config(seed, BenchmarkSpec()))
    d = ctx.data
    taus = list(range(d.h0 + step - 1, d.H, step))
    fr = ctx.features.frame(taus, run_id=str(seed))
    events = [{"type": e.type, "feeder": e.feeder, "dt": e.dt, "consumers": e.consumers, "start": e.start_hour,
               "end": e.end_hour} for e in d.events if e.theft_like]
    return fr, events


def _eb_worker(args):
    """Energy-balance recovery: injected unmetered energy vs. unexplained energy (scenario - normal)."""
    seed, magnitude = args
    from ..pipeline import prepare

    r = np.random.default_rng(seed)
    f = f"F{int(r.integers(1, 5))}"
    dt = f"{f}-DT{int(r.integers(1, 4))}"
    inj = Injection(type="unmetered_load", feeder=f, dt=dt, magnitude=magnitude, onset_day=3.0, duration_days=8.0)
    scen = prepare(SimulationConfig(scenario="C", seed=seed, injections=[inj]))
    base = prepare(SimulationConfig(scenario="A", seed=seed))
    d = scen.data
    a, b = d.h0 + 72, d.h0 + 72 + 192
    out = {"seed": seed, "feeder": f, "dt": dt, "magnitude_pct": magnitude}
    k = d.dt_ids.index(dt)
    out["injected_kwh"] = float(d.unmetered_kw[k, a:b].sum())
    true_extra_loss = (sum(d.true_loss_kwh[x][d.feeder_ids.index(f), a:b].sum() for x in ("mv", "dt_cu", "dt_core", "lv"))
                       - sum(base.data.true_loss_kwh[x][d.feeder_ids.index(f), a:b].sum()
                             for x in ("mv", "dt_cu", "dt_core", "lv")))
    out["true_extra_losses_kwh"] = float(true_extra_loss)
    for kind, uid in (("dt", dt), ("feeder", f)):
        u_s = scen.accountant.balance(kind, uid, a, b, b - 1)
        u_b = base.accountant.balance(kind, uid, a, b, b - 1)
        out[f"{kind}_unexplained_kwh"] = u_s["unexplained_kwh"]
        out[f"{kind}_unexplained_normal_kwh"] = u_b["unexplained_kwh"]
        out[f"{kind}_z"] = u_s["z_score"]
        out[f"{kind}_z_normal"] = u_b["z_score"]
        out[f"{kind}_recovered_kwh"] = u_s["unexplained_kwh"] - u_b["unexplained_kwh"]
    return out


# --------------------------------------------------------------------------- helpers
def _score_all(bundle: ModelBundle, fr: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    cs = bundle.score_consumers(fr["consumer"])
    return {"consumer": cs, "dt": bundle.score_units("dt", fr["dt"], fr["consumer"], cs),
            "feeder": bundle.score_units("feeder", fr["feeder"], fr["consumer"], cs)}


def _table(bundle, fr, sc, level: str, methods: dict, n_boot: int, tuned_rules: bool = False) -> list[dict]:
    df = fr[level]
    y, runs = df["label"].to_numpy(), df["run"].to_numpy()
    rows = []
    for m, info in methods.items():
        thr = bundle.threshold(m, level, tuned_rules=tuned_rules)
        res = evaluate(y, sc[level][m].to_numpy(), thr, runs, n_boot=n_boot)
        rows.append({"method": m, "name": info["name"], "family": info["family"], "signals": info["signals"],
                     "threshold": thr, "threshold_source": "configured rule threshold" if (
                         info["family"] == "rule" and not tuned_rules) else "max-F1 on validation runs", **res})
    return rows


def _sweep(bundle, label: str, levels: list, spec_for, seeds: list[int], n_boot: int) -> dict:
    res = {"levels": levels, "consumer": {m: [] for m in SWEEP_METHODS_C}, "feeder": {m: [] for m in SWEEP_METHODS_U}}
    for lv in levels:
        t0 = time.perf_counter()
        fr = _frames(seeds, spec_for(lv))
        sc = _score_all(bundle, fr)
        for level, methods in (("consumer", SWEEP_METHODS_C), ("feeder", SWEEP_METHODS_U)):
            df = fr[level]
            y, runs = df["label"].to_numpy(), df["run"].to_numpy()
            for m in methods:
                r = evaluate(y, sc[level][m].to_numpy(), bundle.threshold(m, level), runs, n_boot=n_boot)
                res[level][m].append({"level": lv, **{k: r[k] for k in ("precision", "recall", "f1", "fpr", "roc_auc",
                                                                        "pr_auc", "ci95", "n_pos", "n_neg")}})
        log.info("sweep %s=%s done in %.0f s", label, lv, time.perf_counter() - t0)
    return res


def _delays(bundle, seeds: list[int], step: int) -> dict:
    with ProcessPoolExecutor(WORKERS) as ex:
        parts = list(ex.map(_delay_worker, [(s, step) for s in seeds]))
    per_method: dict[str, list] = {}
    for fr, events in parts:
        sc = _score_all(bundle, fr)
        cdf = fr["consumer"]
        for m in SWEEP_METHODS_C:
            thr = bundle.threshold(m, "consumer")
            flag = sc["consumer"][m].to_numpy() >= thr
            for ev in events:
                if ev["type"] == "unmetered_load":
                    continue
                for cid in ev["consumers"]:
                    sel = (cdf["unit"].to_numpy() == cid) & (cdf["tau"].to_numpy() >= ev["start"]) & (
                        cdf["tau"].to_numpy() < ev["end"])
                    hit = np.flatnonzero(sel & flag)
                    delay = float(cdf["tau"].to_numpy()[hit[0]] - ev["start"]) if len(hit) else None
                    per_method.setdefault(f"consumer:{m}", []).append(delay)
        for level in ("dt", "feeder"):
            udf = fr[level]
            for m in SWEEP_METHODS_U:
                thr = bundle.threshold(m, level)
                flag = sc[level][m].to_numpy() >= thr
                for ev in events:
                    target = ev["dt"] if level == "dt" else ev["feeder"]
                    if level == "dt" and target is None:
                        continue
                    sel = (udf["unit"].to_numpy() == target) & (udf["tau"].to_numpy() >= ev["start"]) & (
                        udf["tau"].to_numpy() < ev["end"])
                    hit = np.flatnonzero(sel & flag)
                    delay = float(udf["tau"].to_numpy()[hit[0]] - ev["start"]) if len(hit) else None
                    per_method.setdefault(f"{level}:{m}" + (":unmetered" if level == "dt" else ""), []).append(delay)
    out = {}
    for k, v in per_method.items():
        found = [x for x in v if x is not None]
        out[k] = {"events": len(v), "detected": len(found), "detection_rate": len(found) / len(v) if v else None,
                  "median_delay_h": float(np.median(found)) if found else None,
                  "p25_delay_h": float(np.percentile(found, 25)) if found else None,
                  "p75_delay_h": float(np.percentile(found, 75)) if found else None}
    return {"grid_step_hours": step, "seeds": [seeds[0], seeds[-1]], "results": out,
            "definition": "hours from event onset to the first evaluation time (on a grid of every "
                          f"{step} h) at which the method flags the affected consumer (B/D), DT (C) or feeder; "
                          "events never flagged during their window count as missed."}


def _localisation(bundle, seeds: list[int]) -> dict:
    spec = BenchmarkSpec(single_feeder_theft=True)
    fr = _frames(seeds, spec)
    sc = _score_all(bundle, fr)
    out = {}
    for level in ("feeder", "dt"):
        df = fr[level].copy()
        for m in UNIT_METHODS:
            df["s"] = sc[level][m].to_numpy()
            hits, n = 0, 0
            for _, g in df.groupby(["run", "tau"]):
                if (g["label"] == 1).sum() == 0:
                    continue
                n += 1
                hits += int(g.sort_values("s", ascending=False)["label"].iloc[0] == 1)
            out.setdefault(level, {})[m] = {"top1_hit_rate": hits / n if n else None, "n_windows": n}
    return {"seeds": [seeds[0], seeds[-1]], "definition": "share of evaluation windows with at least one theft-like "
            "event in which the highest-scoring feeder (or DT) is one that actually contains the event",
            "results": out}


def _runtime(bundle) -> list[dict]:
    from ..pipeline import prepare

    rows = []
    for nf, nd, cpd in ((4, 3, 10), (4, 3, 25), (4, 3, 50), (4, 3, 80), (6, 4, 80)):
        spec = BenchmarkSpec(n_feeders=nf, dts_per_feeder=nd, consumers_per_dt=cpd)
        cfg = benchmark_config(99, spec)
        t0 = time.perf_counter()
        ctx = prepare(cfg)
        t_gen = time.perf_counter() - t0
        taus = list(range(ctx.data.h0 + 100, ctx.data.h0 + 110))
        t1 = time.perf_counter()
        fts = [ctx.features.at(t) for t in taus]
        t_feat = (time.perf_counter() - t1) / len(taus)
        t2 = time.perf_counter()
        for ft in fts:
            tb = ctx.features.tables(ft)
            cs = bundle.score_consumers(tb["consumer"])
            bundle.score_units("feeder", tb["feeder"], tb["consumer"], cs)
            bundle.score_units("dt", tb["dt"], tb["consumer"], cs)
        t_score = (time.perf_counter() - t2) / len(taus)
        rows.append({"consumers": len(ctx.data.consumer_ids), "feeders": nf, "dts": nf * nd,
                     "hours_generated": ctx.data.H, "readings_generated": int(len(ctx.data.consumer_ids) * ctx.data.H),
                     "generation_and_power_flow_s": round(t_gen, 3), "features_per_step_ms": round(1000 * t_feat, 1),
                     "scoring_per_step_ms": round(1000 * t_score, 1)})
        log.info("runtime %s", rows[-1])
    return rows


def _confounders(fr, sc, bundle) -> list[dict]:
    df = fr["consumer"]
    lab = df["label"].to_numpy()
    benign, fault = df["benign"].to_numpy(), df["fault"].to_numpy()
    rows = []
    for m, info in CONSUMER_METHODS.items():
        flag = sc["consumer"][m].to_numpy() >= bundle.threshold(m, "consumer")
        neg = lab == 0
        g = lambda mask, flag=flag: float(flag[mask].mean()) if mask.sum() else None  # noqa: E731
        rows.append({"method": m, "name": info["name"], "signals": info["signals"],
                     "flag_rate_benign_change": g(neg & benign), "flag_rate_data_fault": g(neg & fault),
                     "flag_rate_other_negatives": g(neg & ~benign & ~fault), "recall_theft_like": g(lab == 1),
                     "n_benign": int((neg & benign).sum()), "n_fault": int((neg & fault).sum())})
    return rows


# --------------------------------------------------------------------------- main
def main(quick: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    T0 = time.perf_counter()
    n_boot = 100 if quick else 300
    train_s, val_s, test_s = (TRAIN_SEEDS[:8], VAL_SEEDS[:4], TEST_SEEDS[:6]) if quick else (TRAIN_SEEDS, VAL_SEEDS,
                                                                                               TEST_SEEDS)
    sweep_n = 4 if quick else 10

    log.info("building train/validation/test frames with %d workers", WORKERS)
    train, val, test = _frames(train_s), _frames(val_s), _frames(test_s)
    bundle = train_bundle(train, val, meta={"train_seeds": [train_s[0], train_s[-1]],
                                            "val_seeds": [val_s[0], val_s[-1]], "benchmark_spec": "BenchmarkSpec()"})
    if not quick:
        bundle.save()  # the API serves exactly the models evaluated here
    sc = _score_all(bundle, test)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for level in ("consumer", "dt", "feeder"):
        out = pd.concat([test[level][["run", "tau", "unit", "label"]], sc[level]], axis=1)
        out.to_csv(RESULTS_DIR / f"test_predictions_{level}.csv.gz", index=False)

    results: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "quick": quick,
        "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                        "platform": platform.platform(), "workers": WORKERS},
        "benchmark": {"spec": describe_spec(BenchmarkSpec()), "train_seeds": [train_s[0], train_s[-1], len(train_s)],
                      "val_seeds": [val_s[0], val_s[-1], len(val_s)], "test_seeds": [test_s[0], test_s[-1], len(test_s)],
                      "unit_of_evaluation": "24 h window ending at the end of each simulated day (14 per run); "
                                            "label 1 if a theft-like event is active >= 12 of the 24 h, 0 if none, "
                                            "windows with 1-11 active hours are excluded",
                      "test_counts": {lv: {"windows": int((test[lv]["label"] >= 0).sum()),
                                           "positives": int((test[lv]["label"] == 1).sum())}
                                      for lv in ("consumer", "dt", "feeder")}},
        "model_meta": {k: v for k, v in bundle.meta.items() if k != "feature_sets"},
        "thresholds": bundle.thresholds,
    }
    log.info("main comparison")
    results["main"] = {
        "consumer": _table(bundle, test, sc, "consumer", CONSUMER_METHODS, n_boot),
        "dt": _table(bundle, test, sc, "dt", UNIT_METHODS, n_boot),
        "feeder": _table(bundle, test, sc, "feeder", UNIT_METHODS, n_boot),
    }
    results["rules_tuned_on_validation"] = {
        "consumer": [r for r in _table(bundle, test, sc, "consumer", CONSUMER_METHODS, n_boot, tuned_rules=True)
                     if r["family"] == "rule"],
        "feeder": [r for r in _table(bundle, test, sc, "feeder", UNIT_METHODS, n_boot, tuned_rules=True)
                   if r["family"] == "rule"]}
    results["confounders"] = _confounders(test, sc, bundle)
    pairs = [("consumer", "rf_combined", "rf_consumer"), ("consumer", "combined_rule", "consumer_rule"),
             ("consumer", "if_combined", "if_consumer"), ("consumer", "rf_combined", "consumer_rule"),
             ("feeder", "rf_unit_combined", "rf_consumer_max"), ("feeder", "rf_unit_combined", "balance_rule"),
             ("dt", "rf_unit_combined", "rf_consumer_max"), ("dt", "rf_unit_combined", "balance_rule")]
    results["paired_comparisons"] = []
    for level, a, b_ in pairs:
        df = test[level]
        res = paired_difference(df["label"].to_numpy(), sc[level][a].to_numpy(), bundle.threshold(a, level),
                                sc[level][b_].to_numpy(), bundle.threshold(b_, level), df["run"].to_numpy(),
                                n_boot=200 if quick else 1000)
        results["paired_comparisons"].append({"level": level, "a": a, "b": b_, **res})
    rf_imp = bundle.rf_combined.feature_importances_
    from ..features.build import COMBINED_FEATURES
    results["rf_combined_importance"] = sorted(
        [{"feature": f, "importance": float(v)} for f, v in zip(COMBINED_FEATURES, rf_imp)], key=lambda r: -r["importance"])

    base = 4000
    log.info("sweeps")
    results["sweeps"] = {
        "prevalence": _sweep(bundle, "prevalence", ["low", "medium", "high"],
                             lambda lv: BenchmarkSpec(prevalence=lv), list(range(base, base + sweep_n)), n_boot),
        "noise": _sweep(bundle, "noise", [0.5, 1.0, 2.0, 4.0], lambda lv: BenchmarkSpec(noise_level=lv),
                        list(range(base + 100, base + 100 + sweep_n)), n_boot),
        "missing": _sweep(bundle, "missing", [0.0, 0.05, 0.10, 0.20], lambda lv: BenchmarkSpec(missing_rate=lv),
                          list(range(base + 200, base + 200 + sweep_n)), n_boot),
        "loss_error": _sweep(bundle, "loss_error", [-40, -20, 0, 20, 40],
                             lambda lv: BenchmarkSpec(loss_error_pct=float(lv), stressors=False),
                             list(range(base + 300, base + 300 + sweep_n)), n_boot),
        "loss_error_uncalibrated": _sweep(bundle, "loss_error_uncalibrated", [-40, -20, 0, 20, 40],
                                          lambda lv: BenchmarkSpec(loss_error_pct=float(lv), stressors=False,
                                                                   loss_calibration=False),
                                          list(range(base + 300, base + 300 + sweep_n)), n_boot),
    }
    log.info("localisation")
    results["localisation"] = _localisation(bundle, list(range(5000, 5000 + (4 if quick else 12))))
    log.info("detection delay")
    results["delay"] = _delays(bundle, test_s[: (3 if quick else 10)], step=3)
    log.info("energy-balance recovery")
    with ProcessPoolExecutor(WORKERS) as ex:
        eb = list(ex.map(_eb_worker, [(6000 + i, m) for i, m in enumerate([10, 20, 30, 40, 60, 80] * (1 if quick else 2))]))
    for r in eb:
        r["dt_recovery_ratio"] = r["dt_recovered_kwh"] / r["injected_kwh"]
        r["feeder_recovery_ratio"] = r["feeder_recovered_kwh"] / r["injected_kwh"]
        r["feeder_recovery_ratio_incl_losses"] = r["feeder_recovered_kwh"] / (r["injected_kwh"] + r["true_extra_losses_kwh"])
    results["energy_balance_recovery"] = {
        "runs": eb,
        "summary": {k: {"mean": float(np.mean([r[k] for r in eb])), "sd": float(np.std([r[k] for r in eb]))}
                    for k in ("dt_recovery_ratio", "feeder_recovery_ratio", "feeder_recovery_ratio_incl_losses")},
        "definition": "recovered = unexplained(scenario C) - unexplained(same seed, normal operation) over an 8-day "
                      "window; ratio = recovered / injected unmetered energy. Feeder ratio > 1 is expected because "
                      "the unmetered load also causes extra technical losses that the loss estimate cannot see.",
    }
    log.info("runtime scaling")
    results["runtime"] = _runtime(bundle)
    results["total_seconds"] = round(time.perf_counter() - T0, 1)

    path = RESULTS_DIR / ("results_quick.json" if quick else "results.json")
    path.write_text(json.dumps(results, indent=1, default=float))
    if not quick:
        from .report import write_report

        write_report(results, PROJECT_DIR / "docs" / "experiments" / "results.md")
    log.info("done in %.0f s -> %s", results["total_seconds"], path)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    main(ap.parse_args().quick)
