# OWNER: P4 | NEEDS: P2 | STATUS: ACTIVE
"""T3 / P4-4: supervised gradient boosting on engineered features.

Trained on synthetic injected labels (and, when available, a public theft benchmark via
:mod:`cascadeguard.theft.public_datasets`). ``HistGradientBoostingClassifier`` handles missing
values natively, so unmetered-DT context and missing reads need no imputation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold

from cascadeguard.theft import load_config

CONSUMER_TYPE_CODE = {"residential": 0, "commercial": 1, "small_industrial": 2}


def model_matrix(features: pd.DataFrame, consumer_type: pd.Series | None = None) -> pd.DataFrame:
    """All ``f_*`` columns plus an integer consumer-type code."""
    x = features[[c for c in features.columns if c.startswith("f_")]].copy()
    if consumer_type is not None:
        x["f_consumer_type"] = consumer_type.map(CONSUMER_TYPE_CODE).fillna(-1).to_numpy()
    return x


class SupervisedTheftModel:
    def __init__(self, config: dict[str, Any] | None = None, seed: int = 42):
        self.cfg = (config or load_config())["models"]
        self.seed = seed
        self.columns: list[str] = []
        self.model = self._new()

    def _new(self) -> HistGradientBoostingClassifier:
        g = self.cfg["gbm"]
        return HistGradientBoostingClassifier(
            max_iter=int(g["max_iter"]), learning_rate=float(g["learning_rate"]),
            max_leaf_nodes=int(g["max_leaf_nodes"]), l2_regularization=float(g["l2_regularization"]),
            class_weight="balanced", random_state=self.seed)

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> "SupervisedTheftModel":
        self.columns = list(x.columns)
        self.model.fit(x.to_numpy(dtype=float), np.asarray(y).astype(int))
        return self

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(x.reindex(columns=self.columns).to_numpy(dtype=float))[:, 1]

    def oof_predict(self, x: pd.DataFrame, y: np.ndarray) -> np.ndarray:
        """Out-of-fold probabilities on the training set (inputs for the fusion stacker)."""
        y = np.asarray(y).astype(int)
        folds = StratifiedKFold(n_splits=int(self.cfg["cv_folds"]), shuffle=True, random_state=self.seed)
        oof = np.zeros(len(y))
        arr = x.to_numpy(dtype=float)
        for tr, te in folds.split(arr, y):
            m = self._new().fit(arr[tr], y[tr])
            oof[te] = m.predict_proba(arr[te])[:, 1]
        return oof

    def feature_importance(self, x: pd.DataFrame, y: np.ndarray, n_repeats: int = 5) -> pd.Series:
        """Permutation importance (drop in average precision) on a held-out set."""
        from sklearn.inspection import permutation_importance
        res = permutation_importance(self.model, x.reindex(columns=self.columns).to_numpy(dtype=float),
                                     np.asarray(y).astype(int), scoring="average_precision",
                                     n_repeats=n_repeats, random_state=self.seed)
        return pd.Series(res.importances_mean, index=self.columns).sort_values(ascending=False)
