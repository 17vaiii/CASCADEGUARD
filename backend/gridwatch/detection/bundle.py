"""Training, scoring and persistence of the detection models.

The same scoring functions are used for training-time validation, for the offline
benchmark and for the live API, so the dashboard shows exactly what was evaluated.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import precision_recall_curve

from ..config import MODELS_DIR
from ..features.build import COMBINED_FEATURES, CONSUMER_FEATURES, UNIT_FEATURES
from .methods import (
    CONSUMER_METHODS, IF_COMBINED_FEATURES, IF_CONSUMER_FEATURES, UNIT_METHODS, one_sided, select,
)

log = logging.getLogger("gridwatch.detection")
BUNDLE_VERSION = 4


@dataclass
class ModelBundle:
    if_consumer: IsolationForest
    if_combined: IsolationForest
    rf_consumer: RandomForestClassifier
    rf_combined: RandomForestClassifier
    rf_unit: dict[str, RandomForestClassifier]
    if_reference: dict[str, np.ndarray]  # sorted training anomaly scores (for percentiles)
    if_feature_ref: dict[str, tuple[np.ndarray, np.ndarray]]  # median, MAD of one-sided features
    thresholds: dict[str, float] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------------------------
    def score_consumers(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[COMBINED_FEATURES].to_numpy(dtype=float)
        out = pd.DataFrame(index=df.index)
        out["consumer_rule"] = df["consumer_rule"].to_numpy()
        out["feeder_balance_rule"] = df["feeder_balance_rule"].to_numpy()
        out["combined_rule"] = df["combined_rule"].to_numpy()
        out["if_consumer"] = -self.if_consumer.score_samples(one_sided(X, COMBINED_FEATURES, IF_CONSUMER_FEATURES))
        out["if_combined"] = -self.if_combined.score_samples(one_sided(X, COMBINED_FEATURES, IF_COMBINED_FEATURES))
        out["rf_consumer"] = self.rf_consumer.predict_proba(select(X, COMBINED_FEATURES, CONSUMER_FEATURES))[:, 1]
        out["rf_combined"] = self.rf_combined.predict_proba(X)[:, 1]
        return out

    def score_units(self, kind: str, unit_df: pd.DataFrame, consumer_df: pd.DataFrame,
                    consumer_scores: pd.DataFrame) -> pd.DataFrame:
        key = "dt" if kind == "dt" else "feeder"
        agg = pd.concat([consumer_df[["run", "tau", key]].rename(columns={key: "unit"}),
                         consumer_scores[["consumer_rule", "if_consumer", "rf_consumer"]]], axis=1)
        mx = agg.groupby(["run", "tau", "unit"], sort=False).max()
        idx = pd.MultiIndex.from_frame(unit_df[["run", "tau", "unit"]])
        mx = mx.reindex(idx)
        out = pd.DataFrame(index=unit_df.index)
        out["balance_rule"] = unit_df["balance_rule"].to_numpy()
        out["consumer_rule_max"] = mx["consumer_rule"].to_numpy()
        out["if_consumer_max"] = mx["if_consumer"].to_numpy()
        out["rf_consumer_max"] = mx["rf_consumer"].to_numpy()
        out["rf_unit_combined"] = self.rf_unit[kind].predict_proba(unit_df[UNIT_FEATURES].to_numpy(dtype=float))[:, 1]
        return out

    def set_inference_jobs(self, n_jobs: int = 1) -> "ModelBundle":
        """Small live batches are faster single-threaded (joblib overhead dominates)."""
        for m in (self.if_consumer, self.if_combined, self.rf_consumer, self.rf_combined, *self.rf_unit.values()):
            m.set_params(n_jobs=n_jobs)
        return self

    def threshold(self, method: str, level: str = "consumer", tuned_rules: bool = False) -> float:
        """Decision threshold. Rules use their configured threshold (score 1.0) unless
        `tuned_rules`; ML methods use the validation-selected threshold."""
        info = CONSUMER_METHODS.get(method) if level == "consumer" else UNIT_METHODS.get(method)
        if info and info["family"] == "rule" and not tuned_rules:
            return 1.0
        return self.thresholds.get(f"{level}:{method}", 1.0)

    def if_percentile(self, method: str, scores: np.ndarray) -> np.ndarray:
        ref = self.if_reference[method]
        return 100.0 * np.searchsorted(ref, scores, side="right") / len(ref)

    # ------------------------------------------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        path = path or MODELS_DIR / "bundle.joblib"
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        (path.parent / "bundle_meta.json").write_text(json.dumps(self.meta | {"thresholds": self.thresholds},
                                                                 indent=2, default=str))
        return path

    @staticmethod
    def load(path: Path | None = None) -> "ModelBundle | None":
        path = path or MODELS_DIR / "bundle.joblib"
        if not path.exists():
            return None
        try:
            b = joblib.load(path)
        except Exception as exc:  # incompatible pickle (e.g. scikit-learn upgraded)
            log.warning("could not load model bundle (%s); it will be retrained", exc)
            return None
        if b.meta.get("bundle_version") != BUNDLE_VERSION or b.meta.get("sklearn") != sklearn.__version__:
            log.warning("model bundle is stale (version mismatch); it will be retrained")
            return None
        return b.set_inference_jobs(1)


def best_f1_threshold(y: np.ndarray, s: np.ndarray) -> float:
    """Threshold maximising F1 on validation data (ties -> highest threshold)."""
    m = np.isfinite(s)
    y, s = y[m], s[m]
    if y.sum() == 0:
        return float(np.max(s)) + 1e-9
    p, r, t = precision_recall_curve(y, s)
    with np.errstate(divide="ignore", invalid="ignore"):
        f1 = np.where(p[:-1] + r[:-1] > 0, 2 * p[:-1] * r[:-1] / (p[:-1] + r[:-1]), 0.0)
    best = np.flatnonzero(f1 >= f1.max() - 1e-12)[-1]
    return float(t[best])


def train_bundle(train: dict[str, pd.DataFrame], val: dict[str, pd.DataFrame], meta: dict | None = None,
                 n_estimators: int = 150, random_state: int = 0) -> ModelBundle:
    t0 = time.perf_counter()
    c = train["consumer"]
    X = c[COMBINED_FEATURES].to_numpy(dtype=float)
    lab = c["label"].to_numpy()
    sup = lab >= 0

    # Unsupervised: fitted on all training windows without using labels.
    Xi_c = one_sided(X, COMBINED_FEATURES, IF_CONSUMER_FEATURES)
    Xi_g = one_sided(X, COMBINED_FEATURES, IF_COMBINED_FEATURES)
    if_c = IsolationForest(n_estimators=200, random_state=random_state, n_jobs=-1).fit(Xi_c)
    if_g = IsolationForest(n_estimators=200, random_state=random_state, n_jobs=-1).fit(Xi_g)
    if_ref = {"if_consumer": np.sort(-if_c.score_samples(Xi_c)), "if_combined": np.sort(-if_g.score_samples(Xi_g))}
    mad = lambda A: (np.median(A, axis=0), np.median(np.abs(A - np.median(A, axis=0)), axis=0) + 1e-6)  # noqa: E731
    if_feat_ref = {"if_consumer": mad(Xi_c), "if_combined": mad(Xi_g)}

    rf_kw = dict(n_estimators=n_estimators, min_samples_leaf=3, max_features="sqrt",
                 class_weight="balanced_subsample", n_jobs=-1, random_state=random_state)
    rf_c = RandomForestClassifier(**rf_kw).fit(select(X[sup], COMBINED_FEATURES, CONSUMER_FEATURES), lab[sup])
    rf_g = RandomForestClassifier(**rf_kw).fit(X[sup], lab[sup])
    rf_unit = {}
    for kind in ("dt", "feeder"):
        u = train[kind]
        m = u["label"].to_numpy() >= 0
        rf_unit[kind] = RandomForestClassifier(**rf_kw).fit(u.loc[m, UNIT_FEATURES].to_numpy(dtype=float),
                                                            u.loc[m, "label"].to_numpy())

    bundle = ModelBundle(if_consumer=if_c, if_combined=if_g, rf_consumer=rf_c, rf_combined=rf_g, rf_unit=rf_unit,
                         if_reference=if_ref, if_feature_ref=if_feat_ref)

    # Decision thresholds: maximise F1 on the validation runs (never on test runs).
    vc = val["consumer"]
    vs = bundle.score_consumers(vc)
    vm = vc["label"].to_numpy() >= 0
    for method in CONSUMER_METHODS:
        bundle.thresholds[f"consumer:{method}"] = best_f1_threshold(vc["label"].to_numpy()[vm],
                                                                    vs[method].to_numpy()[vm])
    for kind in ("dt", "feeder"):
        vu = val[kind]
        us = bundle.score_units(kind, vu, vc, vs)
        um = vu["label"].to_numpy() >= 0
        for method in UNIT_METHODS:
            bundle.thresholds[f"{kind}:{method}"] = best_f1_threshold(vu["label"].to_numpy()[um],
                                                                      us[method].to_numpy()[um])
    bundle.meta = {
        "bundle_version": BUNDLE_VERSION, "sklearn": sklearn.__version__,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "training_seconds": round(time.perf_counter() - t0, 1),
        "n_train_consumer_windows": int(len(c)), "n_train_labelled": int(sup.sum()),
        "n_train_positive": int((lab == 1).sum()), "n_val_consumer_windows": int(len(vc)),
        "rf_params": {k: v for k, v in rf_kw.items() if k != "n_jobs"}, "if_params": {"n_estimators": 200},
        "feature_sets": {"consumer": CONSUMER_FEATURES, "combined": COMBINED_FEATURES, "unit": UNIT_FEATURES,
                         "if_consumer": IF_CONSUMER_FEATURES, "if_combined": IF_COMBINED_FEATURES},
        "threshold_rule": "max F1 on validation runs",
    } | (meta or {})
    return bundle.set_inference_jobs(1)
