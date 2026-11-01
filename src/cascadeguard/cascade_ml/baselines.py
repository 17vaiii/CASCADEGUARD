# OWNER: P3 | STATUS: ACTIVE
"""Classical ML baselines (Random Forest, Logistic Regression, Gradient Boosting).

Implements P3-2 benchmark comparison against the Cascade GNN.
"""

from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, mean_absolute_error


def extract_tabular_features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract flat tabular features from cascade scenario records.
    
    Features:
      - load_scale (float)
      - contingency_k (int)
      - num_initial_trips (int)
      - mean_pre_line_loading (float)
      - max_pre_line_loading (float)
      - min_pre_bus_vm (float)
      - total_pre_p_mw (float)
      - season encoding (one-hot: monsoon, post_monsoon, summer)
    
    Returns:
      (X, y_cascade_binary, y_load_loss_mw)
    """
    rows = []
    y_cascade = []
    y_loss = []

    for _, row in df.iterrows():
        load_scale = float(row.get("load_scale", 1.0))
        k = int(row.get("contingency_k", 1))
        raw_init = row.get("initial_trips")
        initial_trips = list(raw_init) if raw_init is not None else []

        raw_fail = row.get("failed_lines")
        failed_lines = list(raw_fail) if raw_fail is not None else []

        raw_load = row.get("pre_line_loading_pct")
        loadings = np.asarray(raw_load if raw_load is not None else [0.0], dtype=float)

        raw_vm = row.get("pre_bus_vm_pu")
        vms = np.asarray(raw_vm if raw_vm is not None else [1.0], dtype=float)

        raw_p = row.get("pre_bus_p_mw")
        p_mws = np.asarray(raw_p if raw_p is not None else [0.0], dtype=float)

        season = str(row.get("season", "monsoon"))
        s_monsoon = 1.0 if season == "monsoon" else 0.0
        s_post = 1.0 if season == "post_monsoon" else 0.0
        s_summer = 1.0 if season == "summer" else 0.0

        feat = [
            load_scale,
            float(k),
            float(len(initial_trips)),
            float(np.mean(loadings)),
            float(np.max(loadings)),
            float(np.min(vms)),
            float(np.sum(p_mws)),
            s_monsoon,
            s_post,
            s_summer,
        ]
        rows.append(feat)

        has_propagation = 1 if len(failed_lines) > len(initial_trips) else 0
        y_cascade.append(has_propagation)

        loss = float(row.get("bengaluru_load_lost_mw", row.get("load_lost_mw", 0.0)))
        y_loss.append(loss)

    X = np.asarray(rows, dtype=np.float32)
    y_cascade = np.asarray(y_cascade, dtype=np.int64)
    y_loss = np.asarray(y_loss, dtype=np.float32)
    return X, y_cascade, y_loss


class TabularBaselines:
    """Trains and evaluates tabular baselines on cascade datasets."""

    def __init__(self, random_state: int = 42):
        self.rf_clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=random_state, n_jobs=-1)
        self.rf_reg = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=random_state, n_jobs=-1)
        self.log_reg = LogisticRegression(max_iter=500, random_state=random_state)
        self.ridge = Ridge(alpha=1.0, random_state=random_state)

    def fit(self, X_train: np.ndarray, y_cascade_train: np.ndarray, y_loss_train: np.ndarray) -> None:
        self.rf_clf.fit(X_train, y_cascade_train)
        self.rf_reg.fit(X_train, y_loss_train)
        self.log_reg.fit(X_train, y_cascade_train)
        self.ridge.fit(X_train, y_loss_train)

    def evaluate(self, X_test: np.ndarray, y_cascade_test: np.ndarray, y_loss_test: np.ndarray) -> dict[str, Any]:
        rf_pred = self.rf_clf.predict(X_test)
        rf_probs = self.rf_clf.predict_proba(X_test)[:, 1]
        rf_loss_pred = self.rf_reg.predict(X_test)

        log_pred = self.log_reg.predict(X_test)
        log_probs = self.log_reg.predict_proba(X_test)[:, 1]
        ridge_loss_pred = self.ridge.predict(X_test)

        return {
            "random_forest": {
                "accuracy": float(accuracy_score(y_cascade_test, rf_pred)),
                "f1": float(f1_score(y_cascade_test, rf_pred, zero_division=0)),
                "roc_auc": float(roc_auc_score(y_cascade_test, rf_probs)),
                "load_loss_mae": float(mean_absolute_error(y_loss_test, rf_loss_pred)),
            },
            "logistic_regression": {
                "accuracy": float(accuracy_score(y_cascade_test, log_pred)),
                "f1": float(f1_score(y_cascade_test, log_pred, zero_division=0)),
                "roc_auc": float(roc_auc_score(y_cascade_test, log_probs)),
                "load_loss_mae": float(mean_absolute_error(y_loss_test, ridge_loss_pred)),
            },
        }
