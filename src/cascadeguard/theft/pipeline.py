# OWNER: P4 | NEEDS: P1,P2,P3 | STATUS: ACTIVE
"""End-to-end P4 pipeline: simulate -> T1/T2 -> T3/T7 -> T4 -> P4-6 -> T5/T6/T10 -> P4-11 -> T9 -> T8.

Run from the repository root::

    PYTHONPATH=src python -m cascadeguard.theft.pipeline            # full run (~5-10 min, CPU)
    PYTHONPATH=src python -m cascadeguard.theft.pipeline --quick    # small smoke run

Outputs (gitignored):

* ``data/processed/theft/`` - simulated dataset, balances, heatmap, features, scores, leads, T9/T8 tables
* ``data/models/theft/theft_bundle.joblib`` - models for :mod:`cascadeguard.theft.service`
* ``data/models/theft/theft_metrics.json`` - every reported metric
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from cascadeguard.theft import DISCLAIMER, REPO_ROOT, load_config
from cascadeguard.theft import energy_balance as eb
from cascadeguard.theft.anomaly import UnsupervisedDetectors
from cascadeguard.theft.case_retrieval import TheftCaseBase, outcome_labels, retrieval_precision
from cascadeguard.theft.fairness import fairness_report
from cascadeguard.theft.features import consumer_features, context_features
from cascadeguard.theft.feeder_sim import DistributionDataset, simulate_distribution
from cascadeguard.theft.fusion import FusionModel, temperature_scaled
from cascadeguard.theft.graph_theft import build_theft_graph, train_graph_model
from cascadeguard.theft.inspection import build_lead_table, compare_strategies
from cascadeguard.theft.metrics import expected_calibration_error, ranking_metrics
from cascadeguard.theft.reason_codes import consumer_reason_codes, network_reason_codes, summary_sentence
from cascadeguard.theft.supervised import SupervisedTheftModel, model_matrix
from cascadeguard.theft.tamper_signals import tamper_features, tamper_only_score, tamper_summary

UNMETERED_TYPES = ("hooking", "night_tapping")


def _log(msg: str) -> None:
    print(f"[p4 {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def build_feature_table(ds: DistributionDataset, fb: eb.BalanceResult, db: eb.BalanceResult,
                        cfg: dict[str, Any]) -> pd.DataFrame:
    c = ds.consumers
    f = consumer_features(ds.metered_kwh, ds.timestamps, ds.history_end, c, cfg)
    f = f.join(tamper_features(ds.tamper_log, c.consumer_id, ds.history_end, ds.n_periods, ds.interval_hours))
    return f.join(context_features(c, fb.summary, db.summary))


def fit_consumer_models(F: pd.DataFrame, ctype: pd.Series, y: np.ndarray, fit_mask: np.ndarray,
                        cal_mask: np.ndarray, cfg: dict[str, Any], seed: int,
                        unsup: UnsupervisedDetectors | None = None) -> dict[str, Any]:
    """Fit unsupervised (no labels), supervised (OOF for stacking) and fusion; score every row."""
    if unsup is None:
        unsup = UnsupervisedDetectors(cfg, seed).fit(F[fit_mask])
    scores = unsup.score(F)
    X = model_matrix(F, ctype)
    sup = SupervisedTheftModel(cfg, seed)
    oof = sup.oof_predict(X[fit_mask], y[fit_mask])
    sup.fit(X[fit_mask], y[fit_mask])
    scores["s_gbm"] = sup.predict_proba(X)
    stack = F.join(scores)
    stack_fit = stack[fit_mask].copy()
    stack_fit["s_gbm"] = oof
    fusion = FusionModel(alpha=float(cfg["fusion"]["conformal_alpha"])).fit(
        stack_fit, y[fit_mask], stack[cal_mask], y[cal_mask], seed)
    return {"unsupervised": unsup, "supervised": sup, "fusion": fusion, "scores": scores,
            "prob": fusion.predict_proba(stack), "stack": stack}


def cross_fit_probabilities(F: pd.DataFrame, ctype: pd.Series, y: np.ndarray, cfg: dict[str, Any],
                            seed: int, unsup: UnsupervisedDetectors, folds: int = 5) -> np.ndarray:
    """Out-of-fold fused probability for *every* consumer (used for inspection and fairness)."""
    out = np.zeros(len(y))
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    rng = np.random.default_rng(seed)
    for tr, te in skf.split(np.zeros(len(y)), y):
        cal_pick = rng.random(len(tr)) < 0.2
        fit_mask = np.zeros(len(y), dtype=bool)
        cal_mask = np.zeros(len(y), dtype=bool)
        fit_mask[tr[~cal_pick]] = True
        cal_mask[tr[cal_pick]] = True
        res = fit_consumer_models(F, ctype, y, fit_mask, cal_mask, cfg, seed, unsup)
        out[te] = res["prob"][te]
    return out


def dt_lead_probability(dt_summary: pd.DataFrame, true_dt_unmetered: pd.Series, seed: int) -> pd.Series:
    """Out-of-fold logistic mapping from DT residual evidence to P(unmetered theft at the DT)."""
    s = dt_summary.set_index("node_id")
    x = np.column_stack([np.sign(s.z) * np.log1p(np.abs(s.z)), s.peak_change_pct.fillna(0.0)])
    y = (true_dt_unmetered.reindex(s.index).fillna(0.0) > 1.0).astype(int).to_numpy()
    if y.sum() < 3 or y.sum() > len(y) - 3:
        return pd.Series(np.clip(x[:, 0] / 5.0, 0, 1), index=s.index)
    lr = LogisticRegression(max_iter=1000)
    folds = min(5, int(y.sum()), int(len(y) - y.sum()))
    prob = cross_val_predict(lr, x, y, cv=StratifiedKFold(folds, shuffle=True, random_state=seed),
                             method="predict_proba")[:, 1]
    return pd.Series(prob, index=s.index)


def run_pipeline(out_dir: str | Path = REPO_ROOT / "data" / "processed" / "theft",
                 model_dir: str | Path = REPO_ROOT / "data" / "models" / "theft",
                 scale: float = 2.0, seed: int | None = None, run_t9: bool = True, run_t8: bool = True,
                 n_jobs: int = 4, config: dict[str, Any] | None = None, track: bool = False) -> dict[str, Any]:
    cfg = config or load_config()
    seed = int(cfg.get("seed", 42) if seed is None else seed)
    out_dir, model_dir = Path(out_dir), Path(model_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    metrics: dict[str, Any] = {"seed": seed, "scale": scale, "disclaimer": DISCLAIMER}

    # -- data -----------------------------------------------------------------
    _log(f"simulating distribution layer (scale={scale})")
    ds = simulate_distribution(cfg, seed=seed, scale=scale)
    ds.save(out_dir / "dataset")
    c = ds.consumers
    metrics["dataset"] = {
        "feeders": int(len(ds.feeders)), "dts": int(len(ds.dts)), "dts_metered": int(ds.dts.metered.sum()),
        "consumers": int(len(c)), "periods": int(ds.n_periods), "history_end": int(ds.history_end),
        "theft_by_type": c.theft_type.value_counts().to_dict(),
        "lookalikes": c.lookalike_type.value_counts().to_dict(), "comm_gaps": int(c.comm_gap.sum()),
        "split": c.split.value_counts().to_dict(),
    }

    # -- T1 / T2 ----------------------------------------------------------------
    _log("T1/T2: technical loss and energy balance")
    from cascadeguard.grid.corridor_model import build_corridor_network
    from cascadeguard.theft.technical_loss import corridor_line_losses, corridor_loss_summary
    corridor = build_corridor_network()
    import pandapower as pp
    pp.runpp(corridor, algorithm="nr", init="dc", numba=False)
    corridor_line_losses(corridor).to_parquet(out_dir / "corridor_section_losses.parquet", index=False)
    fb = eb.feeder_balance(ds, cfg["energy_balance"]["flag_z"])
    db = eb.dt_balance(ds, cfg["energy_balance"]["flag_z"])
    fb.daily.to_parquet(out_dir / "feeder_balance_daily.parquet", index=False)
    db.daily.to_parquet(out_dir / "dt_balance_daily.parquet", index=False)
    fb.summary.to_parquet(out_dir / "feeder_balance_summary.parquet", index=False)
    db.summary.to_parquet(out_dir / "dt_balance_summary.parquet", index=False)
    eb.residual_heatmap(fb).reset_index().to_parquet(out_dir / "feeder_residual_heatmap.parquet", index=False)
    ratio = eb.ntl_ratio_by_substation(ds, fb)
    ratio.to_parquet(out_dir / "ntl_ratio_by_substation.parquet", index=False)
    curve_err = [v["feeder"].max_rel_error for v in ds.curves.values()]
    metrics["technical_loss"] = {
        "corridor": corridor_loss_summary(corridor),
        "feeder_curve_max_rel_error": float(max(curve_err)),
        "split_history": eb.loss_split(ds, fb, "history"), "split_recent": eb.loss_split(ds, fb, "recent"),
    }
    top_n = int(cfg["energy_balance"]["top_n_feeders"])
    metrics["energy_balance"] = {
        "feeder_localisation": eb.localisation_accuracy(fb.summary, eb.true_ntl_by_node(ds, "feeder_id"), top_n),
        "dt_localisation": eb.localisation_accuracy(db.summary, eb.true_ntl_by_node(ds, "dt_id"), 2 * top_n),
        "ntl_ratio_by_substation": ratio.to_dict(orient="records"),
        "feeders_with_unbilled_new_connection": int(ds.feeders.new_connection.sum()),
    }

    # -- T3 / T7 features and models ---------------------------------------------
    _log("T3/T7: features and consumer models")
    F = build_feature_table(ds, fb, db, cfg)
    F.reset_index().to_parquet(out_dir / "consumer_features.parquet", index=False)
    y = c.is_theft.to_numpy().astype(int)
    split = c.split.to_numpy()
    types = c.theft_type.to_numpy()
    ctype = c.set_index("consumer_id").consumer_type.reindex(F.index)
    train, val, test = split == "train", split == "validation", split == "test"
    res = fit_consumer_models(F, ctype, y, train, val, cfg, seed)
    scores, prob = res["scores"], res["prob"]
    k = int(cfg["inspection"]["capacity_k"])

    # -- P4-6 graph model -----------------------------------------------------------
    _log("P4-6: graph model")
    gx = F[[col for col in F.columns if col.startswith("f_") and not col.startswith(("f_feeder", "f_dt"))]].join(
        scores[["s_isolation_forest", "s_autoencoder", "s_peer_deviation"]])
    graph, ginfo = build_theft_graph(c, gx, db.summary, fb.summary, ds.dts, ds.feeders)
    g_prob, g_meta = train_graph_model(graph, ginfo["n_consumers"], y, split, cfg, seed)

    # -- evaluation on the held-out test split -----------------------------------------
    candidates = {
        "threshold_baseline": scores.s_threshold_baseline.to_numpy(),
        "tamper_only": tamper_only_score(F),
        "isolation_forest": scores.s_isolation_forest.to_numpy(),
        "autoencoder": scores.s_autoencoder.to_numpy(),
        "peer_deviation": scores.s_peer_deviation.to_numpy(),
        "feeder_residual_only": F.f_feeder_z.fillna(0).to_numpy(),
        "gbm": scores.s_gbm.to_numpy(),
        "graph_sage": g_prob,
        "fusion": prob,
    }
    metrics["consumer_models_test"] = {name: ranking_metrics(y[test], s[test], k, types[test])
                                       for name, s in candidates.items()}
    raw_gbm = scores.s_gbm.to_numpy()
    fusion = res["fusion"]
    metrics["calibration"] = {
        "temperature": fusion.temperature,
        "ece_fusion_uncalibrated": expected_calibration_error(temperature_scaled(prob, 1 / fusion.temperature)[test], y[test]),
        "ece_fusion_calibrated": expected_calibration_error(prob[test], y[test]),
        "ece_gbm_raw": expected_calibration_error(raw_gbm[test], y[test]),
        "conformal_alpha": fusion.alpha, "conformal_q": fusion.conformal_q,
        "conformal_coverage_test": fusion.coverage(prob[test], y[test]),
        "confidence_mix_test": fusion.prediction_sets(prob[test]).confidence.value_counts().to_dict(),
        "fusion_coefficients": fusion.coefficients(),
    }
    iv = fusion.probability_interval(prob[test])
    top_iv = fusion.probability_interval(np.sort(prob[test])[-k:])
    metrics["calibration"]["venn_abers"] = {
        "mean_width_all_test": float((iv[:, 1] - iv[:, 0]).mean()),
        "mean_width_top_k": float((top_iv[:, 1] - top_iv[:, 0]).mean()),
        "mean_low": float(iv[:, 0].mean()), "mean_high": float(iv[:, 1].mean()),
        "observed_rate": float(y[test].mean()),
    }
    metrics["graph_model"] = g_meta
    metrics["gbm_permutation_importance_top"] = res["supervised"].feature_importance(
        model_matrix(F, ctype)[test], y[test]).head(12).to_dict()

    # -- cross-fitted scores for the whole population (inspection + fairness) -------------
    _log("cross-fitting scores for all consumers")
    cf_prob = cross_fit_probabilities(F, ctype, y, cfg, seed, res["unsupervised"])
    metrics["consumer_models_crossfit"] = {
        "fusion": ranking_metrics(y, cf_prob, k, types),
        "threshold_baseline": ranking_metrics(y, candidates["threshold_baseline"], k, types),
        "ece_fusion": expected_calibration_error(cf_prob, y),
    }
    scored = c[["consumer_id", "feeder_id", "dt_id", "substation", "area", "consumer_type", "theft_type",
                "lookalike_type", "is_theft", "split"]].copy()
    scored["prob"] = cf_prob
    scored["prob_test_split_model"] = prob
    scored["graph_prob"] = g_prob
    scored.to_parquet(out_dir / "consumer_scores.parquet", index=False)
    legit = scored[~scored.is_theft.astype(bool)]
    top_n = scored.nlargest(int(scored.is_theft.sum()), "prob")
    metrics["lookalike_false_flags"] = {
        str(kind): {"n": int(len(g)), "false_flag_rate_at_0_5": float((g.prob >= 0.5).mean()),
                    "in_top_n_where_n_is_thefts": int(top_n[~top_n.is_theft.astype(bool)].lookalike_type.eq(kind).sum())}
        for kind, g in legit.groupby("lookalike_type")}

    # -- T6 inspection --------------------------------------------------------------------
    _log("T6: inspection prioritisation")
    ntl = pd.Series(ds.ntl_kwh[:, ds.history_end:].sum(axis=1), index=c.consumer_id.to_numpy())
    metered_types = ~c.theft_type.isin(UNMETERED_TYPES).to_numpy()
    ntl_consumer = ntl.where(metered_types, 0.0)       # what a meter inspection recovers
    ntl_dt_unmetered = pd.Series(np.where(~metered_types, ntl.to_numpy(), 0.0),
                                 index=c.dt_id.to_numpy()).groupby(level=0).sum()
    dt_prob = dt_lead_probability(db.summary, ntl_dt_unmetered, seed)
    leads = build_lead_table(c, F, cf_prob, candidates["threshold_baseline"], ds.n_periods - ds.history_end,
                             db.summary, ds.dts, dt_prob, ntl_consumer, ntl_dt_unmetered)
    depots = {s: (float(x), 0.0) for s, x in ds.feeders.groupby("substation").x_km.first().items()}
    campaign = compare_strategies(leads, k, depots, cfg, seed)
    campaign.to_parquet(out_dir / "inspection_strategies.parquet", index=False)
    metrics["inspection"] = {"capacity_k": k, "strategies": campaign.to_dict(orient="records")}

    # -- T5 + T10: lead list with reasons and precedent ---------------------------------------
    _log("T5/T10: reason codes and similar cases")
    outcomes = outcome_labels(c)
    case_base = TheftCaseBase().fit(F[train], outcomes[train])
    thief_test = test & (y == 1)
    metrics["case_retrieval"] = retrieval_precision(case_base, F[thief_test], outcomes.outcome, 5)
    from cascadeguard.theft.inspection import select
    chosen = select(leads, "value_route", k, depots, cfg["inspection"], seed)
    fsum = db.summary.set_index("node_id")
    lead_rows = []
    for rank, j in enumerate(chosen, start=1):
        lead = leads.iloc[j]
        if lead.lead_type == "consumer":
            fr = F.loc[lead.lead_id]
            meta = c.set_index("consumer_id").loc[lead.lead_id]
            codes = consumer_reason_codes(fr, tamper_summary(ds.tamper_log, lead.lead_id, ds.history_end),
                                          meta.feeder_id, meta.dt_id)
            conf = str(fusion.prediction_sets(np.array([lead.prob])).confidence.iloc[0])
            sim = case_base.query(F.loc[[lead.lead_id]], 5)[0]
            precedent = case_base.precedent_summary(sim)
        else:
            explained = float((leads[(leads.lead_type == "consumer") & (leads.dt_id == lead.lead_id)]
                               .eval("prob * est_kwh")).sum())
            codes = network_reason_codes(lead.lead_id, "dt", fsum.loc[lead.lead_id], explained)
            conf, sim, precedent = "network", [], {}
        lead_rows.append({
            "rank": rank, "lead_id": lead.lead_id, "lead_type": lead.lead_type, "substation": lead.substation,
            "dt_id": lead.dt_id, "score": round(float(lead.prob), 4),
            "score_interval": ([round(float(v), 4) for v in fusion.probability_interval(np.array([lead.prob]))[0]]
                               if lead.lead_type == "consumer" else None), "confidence": conf,
            "expected_kwh_at_stake": round(float(lead.est_kwh), 1),
            "summary": summary_sentence(codes, float(lead.prob), conf) if lead.lead_type == "consumer"
            else codes[0]["text"], "reason_codes": codes, "similar_cases": sim, "precedent": precedent,
            "sim_truth_hit": bool(lead.is_hit),
        })
    (out_dir / "inspection_leads.json").write_text(json.dumps(_jsonable(lead_rows), indent=2), encoding="utf-8")
    metrics["lead_list"] = {"n": len(lead_rows), "hits": int(sum(r["sim_truth_hit"] for r in lead_rows)),
                            "consumer_leads": int(sum(r["lead_type"] == "consumer" for r in lead_rows))}

    # -- P4-11 fairness -----------------------------------------------------------------------
    _log("P4-11: fairness audit")
    metrics["fairness"] = fairness_report(scored, k)

    # -- T9 theft-aware cascade --------------------------------------------------------------
    if run_t9:
        _log("T9: theft-aware cascade experiment (P1 simulator + P3 GNN)")
        from cascadeguard.theft.hidden_load import theft_aware_experiment
        t9 = theft_aware_experiment(ratio, cfg, n_jobs=n_jobs, seed=seed)
        t9["rows"].drop(columns=["trips"]).assign(trips=t9["rows"].trips.astype(str)) \
            .to_parquet(out_dir / "t9_theft_aware_cascade.parquet", index=False)
        metrics["theft_aware_cascade"] = {"summary": t9["summary"], "states": t9["states"]}

    # -- T8 HT tapping ---------------------------------------------------------------------
    if run_t8:
        _log("T8: HT tapping detection")
        from cascadeguard.theft.ht_tapping import evaluate_tapping
        t8 = evaluate_tapping(config=cfg, seed=seed)
        t8.pop("cases").to_parquet(out_dir / "t8_ht_tapping_cases.parquet", index=False)
        metrics["ht_tapping"] = t8

    # -- persist ------------------------------------------------------------------------------
    bundle = {"version": "theft_v1", "config": cfg, "unsupervised": res["unsupervised"],
              "supervised": res["supervised"], "fusion": fusion, "case_base": case_base,
              "trained_on": {"seed": seed, "scale": scale, "consumers": int(train.sum())}}
    joblib.dump(bundle, model_dir / "theft_bundle.joblib")
    metrics["runtime_s"] = round(time.time() - t0, 1)
    (model_dir / "theft_metrics.json").write_text(json.dumps(_jsonable(metrics), indent=2), encoding="utf-8")
    _log(f"done in {metrics['runtime_s']} s -> {model_dir / 'theft_metrics.json'}")

    if track:
        try:
            from cascadeguard.common.tracking import tracked_run
            import mlflow
            flat = {f"{m}.{key}": v for m, d in metrics["consumer_models_test"].items()
                    for key, v in d.items() if isinstance(v, float) and np.isfinite(v)}
            with tracked_run("cascadeguard-p4-theft", run_name=f"pipeline-seed{seed}",
                             params={"seed": seed, "scale": scale}):
                mlflow.log_metrics(flat)
                mlflow.log_metrics({"calibration.ece_fusion": metrics["calibration"]["ece_fusion_calibrated"],
                                    "calibration.conformal_coverage": metrics["calibration"]["conformal_coverage_test"]})
                mlflow.log_artifact(str(model_dir / "theft_metrics.json"))
            _log("logged to MLflow")
        except Exception as exc:  # tracking is optional
            _log(f"MLflow tracking skipped: {exc}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", type=float, default=2.0, help="feeder-count multiplier (2.0 ~ 5k consumers)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--quick", action="store_true", help="small run without T9/T8")
    parser.add_argument("--skip-t9", action="store_true")
    parser.add_argument("--skip-t8", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--track", action="store_true", help="log to MLflow (MLFLOW_TRACKING_URI)")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "data" / "processed" / "theft"))
    parser.add_argument("--model-dir", default=str(REPO_ROOT / "data" / "models" / "theft"))
    a = parser.parse_args()
    scale = 0.5 if a.quick else a.scale
    run_pipeline(a.out_dir, a.model_dir, scale, a.seed, run_t9=not (a.quick or a.skip_t9),
                 run_t8=not (a.quick or a.skip_t8), n_jobs=a.jobs, track=a.track)


if __name__ == "__main__":
    main()
