# OWNER: P4 | STATUS: ACTIVE
"""T4 / P4-5: hybrid theft-suspicion score with calibrated confidence.

Inputs per consumer: unsupervised anomaly scores, supervised probability, tamper evidence and
the network context from the T2 energy balance (feeder / DT residual z-scores). A logistic
stacker combines them, so a consumer with a strong anomaly on a high-residual feeder gets the
highest score (PRD §7.1).

Calibration: temperature scaling on the validation split (the stacker logit is divided by T).
Confidence: split-conformal prediction sets at level ``1 - alpha``; a lead is *high confidence*
only when the set is ``{suspected}``. Each score also gets a probability interval from inductive
Venn-Abers prediction on the same calibration split (a distribution-free interval for a
probability, the binary-outcome counterpart of a conformal interval). ECE is reported by :mod:`cascadeguard.theft.metrics`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

STACK_COLUMNS = [
    "s_isolation_forest", "s_autoencoder", "s_peer_deviation", "s_threshold_baseline", "s_gbm",
    "f_tamper_strong_recent", "f_tamper_total_recent", "f_feeder_z", "f_dt_z", "f_dt_metered",
]


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _prep(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    x = frame.reindex(columns=columns).copy()
    if "s_gbm" in x:
        x["s_gbm"] = _logit(x["s_gbm"].fillna(0.0).to_numpy())
    for col in ("f_feeder_z", "f_dt_z"):
        if col in x:
            x[col] = np.sign(x[col]) * np.log1p(np.abs(x[col]))      # z can be very large
    return x.fillna(0.0).to_numpy(dtype=float)


@dataclass
class FusionModel:
    columns: list[str] = field(default_factory=lambda: list(STACK_COLUMNS))
    alpha: float = 0.10
    temperature: float = 1.0
    conformal_q: float = 1.0
    stacker: Any = None
    cal_scores: Any = None
    cal_y: Any = None

    def fit(self, train: pd.DataFrame, y_train: np.ndarray, val: pd.DataFrame, y_val: np.ndarray,
            seed: int = 42) -> "FusionModel":
        self.columns = [c for c in self.columns if c in train.columns]
        self.stacker = make_pipeline(StandardScaler(),
                                     LogisticRegression(C=1.0, class_weight=None, max_iter=2000,
                                                        random_state=seed))
        self.stacker.fit(_prep(train, self.columns), np.asarray(y_train).astype(int))
        z = self._raw_logit(val)
        yv = np.asarray(y_val).astype(float)

        def nll(t: float) -> float:
            p = np.clip(1 / (1 + np.exp(-z / t)), 1e-9, 1 - 1e-9)
            return float(-np.mean(yv * np.log(p) + (1 - yv) * np.log(1 - p)))

        self.temperature = float(minimize_scalar(nll, bounds=(0.05, 20.0), method="bounded").x)
        p = self.predict_proba(val)
        self.cal_scores, self.cal_y = np.asarray(p, dtype=float), yv
        nonconf = np.where(yv == 1, 1 - p, p)                     # 1 - p(true class)
        n = len(nonconf)
        level = min(1.0, np.ceil((n + 1) * (1 - self.alpha)) / n)
        self.conformal_q = float(np.quantile(nonconf, level, method="higher"))
        return self

    def _raw_logit(self, frame: pd.DataFrame) -> np.ndarray:
        return self.stacker.decision_function(_prep(frame, self.columns))

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-self._raw_logit(frame) / self.temperature))

    def prediction_sets(self, prob: np.ndarray) -> pd.DataFrame:
        """Conformal sets: which labels are plausible at level ``1 - alpha``."""
        prob = np.asarray(prob)
        suspected = (1 - prob) <= self.conformal_q
        normal = prob <= self.conformal_q
        # high: only "suspected" is plausible; low: only "normal"; medium: both or neither
        # (neither = the evidence does not support a confident call either way).
        confidence = np.where(suspected & ~normal, "high", np.where(normal & ~suspected, "low", "medium"))
        return pd.DataFrame({"set_suspected": suspected, "set_normal": normal, "confidence": confidence})

    def probability_interval(self, prob: np.ndarray) -> np.ndarray:
        """Inductive Venn-Abers interval ``[p0, p1]`` for each score, shape [n, 2]."""
        prob = np.atleast_1d(np.asarray(prob, dtype=float))
        out = np.zeros((len(prob), 2))
        for i, s in enumerate(prob):
            for j, label in enumerate((0.0, 1.0)):
                x = np.append(self.cal_scores, s)
                y = np.append(self.cal_y, label)
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(x, y)
                out[i, j] = float(iso.predict([s])[0])
        return out

    def coverage(self, prob: np.ndarray, y: np.ndarray) -> float:
        sets = self.prediction_sets(prob)
        y = np.asarray(y).astype(bool)
        return float(np.where(y, sets.set_suspected, sets.set_normal).mean())

    def coefficients(self) -> dict[str, float]:
        lr = self.stacker[-1]
        return {c: float(w) for c, w in zip(self.columns, lr.coef_[0])}


def temperature_scaled(prob: np.ndarray, temperature: float) -> np.ndarray:
    z = _logit(np.asarray(prob, dtype=float))
    return 1.0 / (1.0 + np.exp(-z / temperature))
