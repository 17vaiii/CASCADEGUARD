"""Evaluation metrics with run-level (cluster) bootstrap confidence intervals.

Windows from the same run are correlated, so confidence intervals resample whole runs
rather than individual windows.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


def threshold_metrics(y: np.ndarray, s: np.ndarray, thr: float) -> dict:
    p = s >= thr
    tp = int((p & (y == 1)).sum())
    fp = int((p & (y == 0)).sum())
    fn = int((~p & (y == 1)).sum())
    tn = int((~p & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": prec, "recall": rec, "f1": f1, "fpr": fp / (fp + tn) if fp + tn else 0.0,
            "fnr": fn / (fn + tp) if fn + tp else 0.0, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def ranking_metrics(y: np.ndarray, s: np.ndarray) -> dict:
    if len(np.unique(y)) < 2:
        return {"roc_auc": None, "pr_auc": None}
    s = np.nan_to_num(s, nan=-1e9)
    return {"roc_auc": float(roc_auc_score(y, s)), "pr_auc": float(average_precision_score(y, s))}


def paired_difference(y: np.ndarray, s_a: np.ndarray, thr_a: float, s_b: np.ndarray, thr_b: float,
                      runs: np.ndarray, n_boot: int = 1000, seed: int = 1) -> dict:
    """Cluster-bootstrap CI of (method A - method B) on the same windows, for F1 and PR-AUC.
    Pairing on identical resamples removes between-run variance shared by both methods."""
    m = y >= 0
    y, s_a, s_b, runs = y[m], s_a[m], s_b[m], runs[m]
    uniq = np.unique(runs)
    idx_by_run = {r: np.flatnonzero(runs == r) for r in uniq}
    rng = np.random.default_rng(seed)
    d_f1, d_pr = [], []
    for _ in range(n_boot):
        idx = np.concatenate([idx_by_run[r] for r in rng.choice(uniq, size=len(uniq), replace=True)])
        yb = y[idx]
        if len(np.unique(yb)) < 2:
            continue
        d_f1.append(threshold_metrics(yb, s_a[idx], thr_a)["f1"] - threshold_metrics(yb, s_b[idx], thr_b)["f1"])
        d_pr.append(average_precision_score(yb, np.nan_to_num(s_a[idx], nan=-1e9))
                    - average_precision_score(yb, np.nan_to_num(s_b[idx], nan=-1e9)))
    point_f1 = threshold_metrics(y, s_a, thr_a)["f1"] - threshold_metrics(y, s_b, thr_b)["f1"]
    point_pr = average_precision_score(y, np.nan_to_num(s_a, nan=-1e9)) - average_precision_score(
        y, np.nan_to_num(s_b, nan=-1e9))
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]  # noqa: E731
    return {"delta_f1": float(point_f1), "delta_f1_ci95": q(d_f1), "p_f1_le_0": float(np.mean(np.array(d_f1) <= 0)),
            "delta_pr_auc": float(point_pr), "delta_pr_auc_ci95": q(d_pr),
            "p_pr_auc_le_0": float(np.mean(np.array(d_pr) <= 0)), "n_boot": len(d_f1)}


def evaluate(y: np.ndarray, s: np.ndarray, thr: float, runs: np.ndarray, n_boot: int = 300,
             seed: int = 0) -> dict:
    """Point estimates + 95 % cluster-bootstrap CIs (resampling runs)."""
    m = y >= 0
    y, s, runs = y[m], s[m], runs[m]
    out = threshold_metrics(y, s, thr) | ranking_metrics(y, s)
    out["n_pos"], out["n_neg"] = int((y == 1).sum()), int((y == 0).sum())
    uniq = np.unique(runs)
    idx_by_run = {r: np.flatnonzero(runs == r) for r in uniq}
    rng = np.random.default_rng(seed)
    keys = ("precision", "recall", "f1", "fpr", "roc_auc", "pr_auc")
    boots = {k: [] for k in keys}
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_run[r] for r in pick])
        yb, sb = y[idx], s[idx]
        tm = threshold_metrics(yb, sb, thr)
        rm = ranking_metrics(yb, sb) if n_boot else {}
        for k in keys:
            v = tm.get(k, rm.get(k))
            if v is not None:
                boots[k].append(v)
    out["ci95"] = {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else None
                   for k, v in boots.items()}
    return out
