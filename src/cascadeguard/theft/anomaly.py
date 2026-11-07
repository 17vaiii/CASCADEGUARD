# OWNER: P4 | NEEDS: P2 | STATUS: ACTIVE
"""T3 / P4-4: unsupervised consumer anomaly models.

* **Isolation Forest** on robust-scaled behaviour features.
* **Autoencoder** (MLP bottleneck) reconstruction error.
* **Peer-group deviation**: drop relative to same-feeder, same-type peers.
* **Threshold baseline** (PRD §10 comparison): a plain "consumption fell" rule.

Unsupervised models are fitted on training consumers *without labels*; higher score means
more unusual. They flag any unusual change (including legitimate ones such as rooftop solar),
which is why they feed the fusion model rather than being used alone.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler

from cascadeguard.theft import load_config
from cascadeguard.theft.features import BEHAVIOUR_COLUMNS


def threshold_baseline_score(features: pd.DataFrame) -> np.ndarray:
    """Simple rule: larger fall of recent vs own history consumption = more suspicious."""
    ratio = features["f_min7_ratio"].fillna(features["f_ratio_recent"]).fillna(1.0)
    return (1.0 - ratio.clip(0.0, 2.0)).to_numpy(dtype=float)


def peer_deviation_score(features: pd.DataFrame) -> np.ndarray:
    """Robust z of the consumer's consumption ratio below its peer median (positive = drop)."""
    z = -features["f_peer_z"].fillna(0.0)
    zeros = 4.0 * (features["f_zero_frac_recent"] - features["f_zero_frac_hist"]).clip(lower=0).fillna(0)
    return (z.clip(lower=-5.0) + zeros).to_numpy(dtype=float)


class UnsupervisedDetectors:
    """Isolation Forest + autoencoder + peer deviation over behaviour features."""

    def __init__(self, config: dict[str, Any] | None = None, seed: int = 42,
                 columns: list[str] | None = None):
        cfg = (config or load_config())["models"]
        self.columns = list(columns or BEHAVIOUR_COLUMNS)
        self.prep = make_pipeline(SimpleImputer(strategy="median"), RobustScaler())
        iso = cfg["isolation_forest"]
        self.iso = IsolationForest(n_estimators=int(iso["n_estimators"]), contamination=iso["contamination"],
                                   random_state=seed)
        ae = cfg["autoencoder"]
        self.ae = MLPRegressor(hidden_layer_sizes=tuple(ae["hidden"]), max_iter=int(ae["max_iter"]),
                               alpha=float(ae["alpha"]), random_state=seed, early_stopping=True)
        self._ae_scale: np.ndarray | None = None

    def _matrix(self, features: pd.DataFrame) -> np.ndarray:
        return features.reindex(columns=self.columns).to_numpy(dtype=float)

    def fit(self, features: pd.DataFrame) -> "UnsupervisedDetectors":
        z = np.clip(self.prep.fit_transform(self._matrix(features)), -10, 10)
        self.iso.fit(z)
        self.ae.fit(z, z)
        self._ae_scale = np.median(np.abs(z - self.ae.predict(z)), axis=0) + 1e-3
        return self

    def score(self, features: pd.DataFrame) -> pd.DataFrame:
        z = np.clip(self.prep.transform(self._matrix(features)), -10, 10)
        recon = np.abs(z - self.ae.predict(z)) / self._ae_scale
        return pd.DataFrame({
            "s_isolation_forest": -self.iso.score_samples(z),
            "s_autoencoder": np.log1p(recon.mean(axis=1)),
            "s_peer_deviation": peer_deviation_score(features),
            "s_threshold_baseline": threshold_baseline_score(features),
        }, index=features.index)
