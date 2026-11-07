# OWNER: P5 | NEEDS: P1,P3,P4 | STATUS: ACTIVE
"""P5 evaluation: no-action vs greedy vs OR-Tools optimizer, case retrieval and warm start.

Run from the repository root::

    PYTHONPATH=src python -m cascadeguard.mitigation.experiment          # ~5-8 min on CPU
    PYTHONPATH=src python -m cascadeguard.mitigation.experiment --quick  # smoke run

Writes ``data/processed/mitigation/`` (per-event results, case library) and
``data/models/mitigation/mitigation_metrics.json``.

Experiments:

1. **Mitigation** (PRD §10 "mitigation vs greedy and no-action", "verification pass rate"):
   every season, all N-1, sampled N-2, loss of the state-grid tie and tie loss + N-1.
2. **Retrieval + warm start** (R8, P5-4/5): cases split into a library and queries;
   precision@k of action type for physics and P3-GNN embeddings; warm vs cold optimizer.
3. **Theft-aware mitigation** (link to P4 T9): with hidden theft load, plans made on the
   SCADA view vs the theft-aware view are verified on the true state.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cascadeguard.mitigation import REPO_ROOT, load_config
from cascadeguard.mitigation.baselines import greedy, no_action
from cascadeguard.mitigation.network import Event, OperatingState, build_state, evaluate_outcome
from cascadeguard.mitigation.verifier import mitigate
from cascadeguard.retrieval.case_library import CascadeCaseLibrary, action_signature, precision_at_k
from cascadeguard.retrieval.warm_start import warm_mitigate


def _log(msg: str) -> None:
    print(f"[p5 {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def events_for(n_lines: int, cfg: dict[str, Any], seed: int) -> list[Event]:
    c = cfg["contingencies"]
    rng = np.random.default_rng(seed)
    events = [Event([i]) for i in range(n_lines)]
    pairs = [(i, j) for i in range(n_lines) for j in range(i + 1, n_lines)]
    for p in rng.choice(len(pairs), size=min(int(c["n2_sample"]), len(pairs)), replace=False):
        events.append(Event(list(pairs[p])))
    if c.get("tie_loss"):
        events.append(Event([], True))
        for li in rng.choice(n_lines, size=int(c["tie_loss_with_n1_sample"]), replace=False):
            events.append(Event([int(li)], True))
    return events


def _run_event(state: OperatingState, event: Event) -> dict[str, Any]:
    before = no_action(state, event)
    row: dict[str, Any] = {"season": state.season, "state": state.label, "event": event.label,
                           "k": len(event.lines), "tie_loss": event.tie_loss,
                           "before_verified": before["verified"], "before_lost_pct": before["load_lost_pct"],
                           "before_lost_mw": before["total_lost_mw"], "before_cascade": before["cascade"],
                           "before_ufls_mw": before["ufls_mw"]}
    if before["verified"]:
        return {"row": {**row, "needs_mitigation": False}, "result": None}
    g = greedy(state, event)
    m = mitigate(state, event, baseline=before)
    rec = m["recommendation"]
    row.update({
        "needs_mitigation": True,
        "greedy_verified": g["verified"], "greedy_lost_pct": g["load_lost_pct"], "greedy_actions": g["n_actions"],
        "greedy_shed_mw": g["explicit_shed_mw"], "greedy_time_s": g["time_s"],
        "opt_stage": m["stage"], "opt_verified": rec["verified"], "opt_lost_pct": rec["load_lost_pct"],
        "opt_actions": rec["n_actions"], "opt_shed_mw": rec["explicit_shed_mw"],
        "opt_tie_delta_mw": rec["actions"]["tie_delta_mw"], "opt_hydro_delta_mw": rec.get("hydro_delta_mw"),
        "opt_hydro_mw": rec.get("hydro_mw"), "hydro_max_mw": state.hydro.max_mw, "hydro_min_mw": state.hydro.min_mw,
        "opt_iterations": rec.get("iterations", 0), "opt_time_s": m["time_s"],
        "opt_solve_time_s": rec.get("solve_time_s", 0.0), "opt_power_flows": rec.get("n_power_flows", 0),
        "signature": action_signature(rec["actions"], rec["verified"]), "actions": json.dumps(rec["actions"]),
    })
    return {"row": row, "result": m}


def _run_state(state: OperatingState, events: list[Event], n_jobs: int) -> list[dict[str, Any]]:
    if n_jobs == 1:
        return [_run_event(state, e) for e in events]
    from joblib import Parallel, delayed
    return Parallel(n_jobs=n_jobs)(delayed(_run_event)(state, e) for e in events)


def theft_aware_mitigation(cfg: dict[str, Any], intensity: float, n_jobs: int, seed: int) -> dict[str, Any]:
    """Plans from the SCADA and theft-aware views, both verified on the true (hidden-load) state."""
    ratio_path = REPO_ROOT / "data" / "processed" / "theft" / "ntl_ratio_by_substation.parquet"
    if not ratio_path.exists():
        return {"status": "skipped", "reason": f"{ratio_path} missing; run the P4 pipeline first"}
    from cascadeguard.theft.hidden_load import hidden_load_vector, metered_substation_mw
    ratio = pd.read_parquet(ratio_path)
    season = "monsoon"
    metered = metered_substation_mw(season)
    truth = build_state(season, hidden_load_vector(ratio, metered, intensity, "true_ntl_ratio"), cfg, "truth")
    aware = build_state(season, hidden_load_vector(ratio, metered, intensity, "est_ntl_ratio"), cfg, "aware")
    scada = build_state(season, None, cfg, "scada")
    events = [Event([i]) for i in range(len(truth.net.line))]

    def one(ev: Event) -> dict[str, Any] | None:
        t = no_action(truth, ev)
        if t["verified"]:
            return None
        from cascadeguard.mitigation.network import Actions
        out = {"event": ev.label, "truth_before_lost_pct": t["load_lost_pct"]}
        for name, view in (("scada", scada), ("aware", aware)):
            plan = mitigate(view, ev)
            acts = Actions.from_dict(plan["recommendation"]["actions"])
            on_truth = evaluate_outcome(truth, ev, acts)
            out[f"{name}_stage"] = plan["stage"]
            out[f"{name}_verified_on_truth"] = on_truth["verified"]
            out[f"{name}_lost_pct_on_truth"] = on_truth["load_lost_pct"]
        return out

    if n_jobs == 1:
        rows = [one(e) for e in events]
    else:
        from joblib import Parallel, delayed
        rows = Parallel(n_jobs=n_jobs)(delayed(one)(e) for e in events)
    rows = [r for r in rows if r]
    df = pd.DataFrame(rows)
    if df.empty:
        return {"status": "ok", "season": season, "intensity": intensity, "events_needing_mitigation": 0}
    return {
        "status": "ok", "season": season, "intensity": intensity,
        "true_hidden_mw": truth.hidden_mw, "est_hidden_mw": aware.hidden_mw,
        "events_needing_mitigation_on_truth": int(len(df)),
        "scada_plans_said_no_action": int((df.scada_stage == "no_action_needed").sum()),
        "scada_plans_verified_on_truth": int(df.scada_verified_on_truth.sum()),
        "aware_plans_verified_on_truth": int(df.aware_verified_on_truth.sum()),
        "mean_lost_pct_on_truth": {"no_action": float(df.truth_before_lost_pct.mean()),
                                   "scada_plan": float(df.scada_lost_pct_on_truth.mean()),
                                   "aware_plan": float(df.aware_lost_pct_on_truth.mean())},
        "rows": df.to_dict(orient="records"),
    }


def summarise(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for season, g in df.groupby("season"):
        need = g[g.needs_mitigation]
        rec: dict[str, Any] = {"season": season, "events": int(len(g)), "needing_mitigation": int(len(need))}
        if len(need):
            for p in ("before", "greedy", "opt"):
                rec[f"{p}_mean_lost_pct"] = float(need[f"{p}_lost_pct"].mean())
            rec["greedy_pass_rate"] = float(need.greedy_verified.mean())
            rec["opt_pass_rate"] = float(need.opt_verified.mean())
            rec["opt_fallback_rate"] = float(need.opt_stage.str.startswith("fallback").mean())
            rec["opt_unverified_rate"] = float(need.opt_stage.str.startswith("unverified").mean())
            ver = need[need.opt_verified & need.greedy_verified]
            rec["both_verified"] = int(len(ver))
            if len(ver):
                rec["opt_mean_actions"] = float(ver.opt_actions.mean())
                rec["greedy_mean_actions"] = float(ver.greedy_actions.mean())
                rec["opt_mean_shed_mw"] = float(ver.opt_shed_mw.mean())
                rec["greedy_mean_shed_mw"] = float(ver.greedy_shed_mw.mean())
            rec["opt_mean_time_s"] = float(need.opt_time_s.mean())
            rec["opt_mean_solve_time_s"] = float(need.opt_solve_time_s.mean())
            rec["hydro_ramp_up_cases"] = int((need.opt_hydro_delta_mw.fillna(0) > 1).sum())
            rec["hydro_ramp_down_cases"] = int((need.opt_hydro_delta_mw.fillna(0) < -1).sum())
            hv = need[need.opt_verified]
            rec["hydro_bound_violations"] = int(((hv.opt_hydro_mw > hv.hydro_max_mw + 0.5) |
                                                 (hv.opt_hydro_mw < hv.hydro_min_mw - 0.5)).sum())
            rec["signatures"] = need.signature.value_counts().to_dict()
        out.append(rec)
    return out


def run_experiment(out_dir: Path = REPO_ROOT / "data" / "processed" / "mitigation",
                   model_dir: Path = REPO_ROOT / "data" / "models" / "mitigation", quick: bool = False,
                   n_jobs: int = 4, config: dict[str, Any] | None = None, run_theft_link: bool = True,
                   track: bool = False) -> dict[str, Any]:
    cfg = config or load_config()
    seed = int(cfg.get("seed", 42))
    out_dir, model_dir = Path(out_dir), Path(model_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    if quick:
        cfg["contingencies"].update({"n2_sample": 6, "tie_loss_with_n1_sample": 3})
    t0 = time.time()
    rows, results = [], []
    states: dict[str, OperatingState] = {}
    for season in ("monsoon", "post_monsoon", "summer"):
        st = build_state(season, None, cfg)
        states[season] = st
        evs = events_for(len(st.net.line), cfg, seed)
        if quick:
            evs = evs[::6]
        _log(f"{season}: {len(evs)} events (tie {st.tie_mw:.0f} MW, hydro {st.hydro.base_mw:.0f} MW, "
             f"max {st.hydro.max_mw:.0f} MW)")
        for ev, res in zip(evs, _run_state(st, evs, n_jobs)):
            rows.append(res["row"])
            if res["result"] is not None:
                results.append((season, ev, res["result"]))
    df = pd.DataFrame(rows)
    df.to_parquet(out_dir / "mitigation_results.parquet", index=False)
    metrics: dict[str, Any] = {"seed": seed, "quick": quick, "config_assumptions": {
        "grid_tie": cfg["grid_tie"], "dispatch": cfg["dispatch"], "limits": cfg["limits"]},
        "states": {s: {"tie_mw": st.tie_mw, "hydro": st.hydro.as_dict(), "load_mw": st.total_load_mw,
                       "capacitors_switched_out": st.net.get("capacitors_switched_out", [])}
                   for s, st in states.items()},
        "mitigation": summarise(df)}

    # -- retrieval + warm start ------------------------------------------------------------
    _log(f"retrieval and warm start over {len(results)} mitigated cases")
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(results))
    n_lib = int(round(len(results) * float(cfg["retrieval"]["library_fraction"])))
    lib_idx, query_idx = order[:n_lib], order[n_lib:]
    k = int(cfg["retrieval"]["k"])
    retrieval: dict[str, Any] = {"library_cases": int(len(lib_idx)), "query_cases": int(len(query_idx)), "k": k}
    libraries = {}
    for kind in ("physics", "gnn"):
        lib = CascadeCaseLibrary(kind)
        for i in lib_idx:
            season, ev, res = results[i]
            lib.add(states[season], ev, res)
        queries = []
        for i in query_idx:
            season, ev, res = results[i]
            v = lib.embed(states[season], ev)
            if v is not None:
                rec = res["recommendation"]
                queries.append((v, action_signature(rec["actions"], rec["verified"])))
        sigs = [c["signature"] for c in lib.cases]
        majority = max(set(sigs), key=sigs.count) if sigs else None
        retrieval[kind] = {"precision_at_k": precision_at_k(lib, queries, k),
                           "precision_at_1": precision_at_k(lib, queries, 1),
                           "majority_class_baseline": float(np.mean([q[1] == majority for q in queries])) if queries else None,
                           "n_vectors": len(lib.vectors)}
        libraries[kind] = lib
    warm_rows = []
    for i in query_idx:
        season, ev, res = results[i]
        w = warm_mitigate(states[season], ev, libraries["physics"], k, before=res["before"])
        seeded = warm_mitigate(states[season], ev, libraries["physics"], k, before=res["before"], try_direct=False)
        cold = res["recommendation"]
        warm_rows.append({"event": f"{season}|{ev.label}", "warm_stage": w["stage"],
                          "warm_verified": w["recommendation"]["verified"], "cold_verified": cold["verified"],
                          "warm_time_s": w["time_s"], "cold_time_s": res["time_s"],
                          "warm_lost_pct": w["recommendation"]["load_lost_pct"], "cold_lost_pct": cold["load_lost_pct"],
                          "warm_actions": w["recommendation"]["n_actions"], "cold_actions": cold["n_actions"],
                          "seeded_verified": seeded["recommendation"]["verified"], "seeded_time_s": seeded["time_s"],
                          "seeded_lost_pct": seeded["recommendation"]["load_lost_pct"],
                          "seeded_actions": seeded["recommendation"]["n_actions"]})
    wdf = pd.DataFrame(warm_rows)
    wdf.to_parquet(out_dir / "warm_start.parquet", index=False)
    if len(wdf):
        retrieval["warm_start"] = {
            "n": int(len(wdf)), "precedent_direct_share": float((wdf.warm_stage == "precedent_direct").mean()),
            "warm_pass_rate": float(wdf.warm_verified.mean()), "cold_pass_rate": float(wdf.cold_verified.mean()),
            "warm_mean_time_s": float(wdf.warm_time_s.mean()), "cold_mean_time_s": float(wdf.cold_time_s.mean()),
            "speedup": float(wdf.cold_time_s.mean() / max(wdf.warm_time_s.mean(), 1e-9)),
            "warm_mean_lost_pct": float(wdf.warm_lost_pct.mean()), "cold_mean_lost_pct": float(wdf.cold_lost_pct.mean()),
            "warm_mean_actions": float(wdf.warm_actions.mean()), "cold_mean_actions": float(wdf.cold_actions.mean()),
            "seeded_pass_rate": float(wdf.seeded_verified.mean()), "seeded_mean_time_s": float(wdf.seeded_time_s.mean()),
            "seeded_mean_lost_pct": float(wdf.seeded_lost_pct.mean()), "seeded_mean_actions": float(wdf.seeded_actions.mean()),
        }
    metrics["retrieval"] = retrieval
    full = CascadeCaseLibrary("physics")
    for season, ev, res in results:
        full.add(states[season], ev, res)
    with open(model_dir / "cascade_case_library.pkl", "wb") as fh:
        pickle.dump(full, fh)

    # -- theft-aware mitigation -------------------------------------------------------------
    if run_theft_link:
        _log("theft-aware mitigation (P4 hidden load)")
        link = theft_aware_mitigation(cfg, 3.0, n_jobs, seed)
        if "rows" in link:
            pd.DataFrame(link.pop("rows")).to_parquet(out_dir / "theft_aware_mitigation.parquet", index=False)
        metrics["theft_aware_mitigation"] = link

    metrics["runtime_s"] = round(time.time() - t0, 1)
    (model_dir / "mitigation_metrics.json").write_text(json.dumps(metrics, indent=2, default=float), encoding="utf-8")
    _log(f"done in {metrics['runtime_s']} s")
    if track:
        from cascadeguard.common.tracking import tracked_run
        import mlflow
        flat: dict[str, float] = {}
        for r in metrics["mitigation"]:
            flat.update({f"{r['season']}.{k}": float(v) for k, v in r.items() if isinstance(v, (int, float))})
        ws = retrieval.get("warm_start", {})
        flat.update({f"warm_start.{k}": float(v) for k, v in ws.items() if isinstance(v, (int, float))})
        flat["retrieval.physics_precision_at_k"] = float(retrieval["physics"]["precision_at_k"])
        with tracked_run("cascadeguard-p5-mitigation", run_name=f"experiment-seed{seed}",
                         params={"seed": seed, "quick": quick}):
            mlflow.log_metrics(flat)
            mlflow.log_artifact(str(model_dir / "mitigation_metrics.json"))
        _log("logged to MLflow")
    return metrics


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--skip-theft-link", action="store_true")
    p.add_argument("--track", action="store_true", help="log to MLflow (MLFLOW_TRACKING_URI)")
    a = p.parse_args()
    run_experiment(quick=a.quick, n_jobs=a.jobs, run_theft_link=not a.skip_theft_link, track=a.track)


if __name__ == "__main__":
    main()
