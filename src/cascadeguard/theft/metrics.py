# OWNER: P4 | STATUS: ACTIVE
"""Evaluation metrics required by PRD §10 (theft pillar)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


def precision_at_k(y: np.ndarray, score: np.ndarray, k: int) -> float:
    order = np.argsort(-np.asarray(score, dtype=float), kind="stable")[:k]
    return float(np.asarray(y)[order].mean()) if k > 0 else float("nan")


def recall_at_k(y: np.ndarray, score: np.ndarray, k: int) -> float:
    y = np.asarray(y)
    order = np.argsort(-np.asarray(score, dtype=float), kind="stable")[:k]
    return float(y[order].sum() / max(y.sum(), 1))


def expected_calibration_error(prob: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    prob, y = np.asarray(prob, dtype=float), np.asarray(y, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(prob, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(prob[m].mean() - y[m].mean())
    return float(ece)


def ranking_metrics(y: np.ndarray, score: np.ndarray, k: int,
                    theft_types: np.ndarray | None = None) -> dict[str, Any]:
    """AUROC, PR-AUC, precision/recall@K and per-type recall@K for one score vector."""
    y = np.asarray(y).astype(int)
    s = np.nan_to_num(np.asarray(score, dtype=float), nan=-1e9)
    out: dict[str, Any] = {
        "n": int(len(y)), "positives": int(y.sum()), "k": int(k),
        "auroc": float(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else float("nan"),
        "pr_auc": float(average_precision_score(y, s)) if y.sum() > 0 else float("nan"),
        "precision_at_k": precision_at_k(y, s, k),
        "recall_at_k": recall_at_k(y, s, k),
        "r_precision": precision_at_k(y, s, int(y.sum())),   # precision at K = number of positives
        "random_precision_at_k": float(y.mean()),
    }
    if theft_types is not None:
        top = np.zeros(len(y), dtype=bool)
        top[np.argsort(-s, kind="stable")[:k]] = True
        types = pd.Series(np.asarray(theft_types))
        out["recall_at_k_by_type"] = {
            t: float(top[(types == t).to_numpy()].mean())
            for t in sorted(types.unique()) if t != "none"
        }
    return out
