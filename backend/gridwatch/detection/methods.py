"""Detection methods compared in this project.

Consumer level (unit = consumer x 24 h window):
    consumer_rule        transparent threshold on peer-adjusted 72 h shortfall (consumer signal only)
    feeder_balance_rule  feeder energy-balance rule; every consumer inherits its feeder's score
                         (feeder signal only — cannot localise inside a feeder)
    combined_rule        consumer rule AND DT energy imbalance (fuzzy AND = min of normalised scores)
    if_consumer          Isolation Forest, consumer features (unsupervised)
    if_combined          Isolation Forest, consumer + grid-context features (unsupervised)
    rf_consumer          Random Forest, consumer features (supervised on synthetic labels)
    rf_combined          Random Forest, consumer + grid-context features (supervised)

Boundary level (unit = DT or feeder x 24 h window):
    balance_rule         energy-balance rule on the boundary itself
    consumer_rule_max    max consumer-rule score inside the boundary
    if_consumer_max      max Isolation-Forest (consumer features) score inside the boundary
    rf_consumer_max      max Random-Forest (consumer features) score inside the boundary
    rf_unit_combined     Random Forest on boundary balance features + consumer aggregates

Scores are method-specific and NOT probabilities of theft:
    rules  -> normalised score, 1.0 = configured threshold
    IF     -> anomaly score (-score_samples); shown as a percentile of training scores
    RF     -> classifier score in [0, 1], fitted to *synthetic* labels; uncalibrated for real data
"""

from __future__ import annotations

import numpy as np

from ..features.build import COMBINED_FEATURES, CONSUMER_FEATURES

CONSUMER_METHODS: dict[str, dict] = {
    "consumer_rule": {"name": "Consumer threshold rule", "family": "rule", "signals": "consumer",
                      "score_kind": "rule score (1.0 = threshold)"},
    "feeder_balance_rule": {"name": "Feeder energy-balance rule", "family": "rule", "signals": "feeder",
                            "score_kind": "rule score (1.0 = threshold)"},
    "combined_rule": {"name": "Combined rule (consumer AND DT balance)", "family": "rule",
                      "signals": "consumer+grid", "score_kind": "rule score (1.0 = threshold)"},
    "if_consumer": {"name": "Isolation Forest (consumer features)", "family": "unsupervised ML",
                    "signals": "consumer", "score_kind": "anomaly score"},
    "if_combined": {"name": "Isolation Forest (consumer + grid features)", "family": "unsupervised ML",
                    "signals": "consumer+grid", "score_kind": "anomaly score"},
    "rf_consumer": {"name": "Random Forest (consumer features)", "family": "supervised ML",
                    "signals": "consumer", "score_kind": "classifier score"},
    "rf_combined": {"name": "Random Forest (consumer + grid features)", "family": "supervised ML",
                    "signals": "consumer+grid", "score_kind": "classifier score"},
}

UNIT_METHODS: dict[str, dict] = {
    "balance_rule": {"name": "Energy-balance rule", "family": "rule", "signals": "boundary balance"},
    "consumer_rule_max": {"name": "Max consumer-rule score", "family": "rule", "signals": "consumer"},
    "if_consumer_max": {"name": "Max Isolation-Forest score (consumer features)", "family": "unsupervised ML",
                        "signals": "consumer"},
    "rf_consumer_max": {"name": "Max Random-Forest score (consumer features)", "family": "supervised ML",
                        "signals": "consumer"},
    "rf_unit_combined": {"name": "Random Forest (balance + consumer aggregates)", "family": "supervised ML",
                         "signals": "boundary balance+consumer"},
}

# One-sided transform for Isolation Forest: map every feature so that larger = more
# suspicious in the under-recording direction, and clip the harmless direction to 0.
# Without this, IF also isolates consumers that use *more* than expected.
_ONE_SIDED: dict[str, str] = {
    "ratio_24": "shortfall", "ratio_72": "shortfall", "ratio_168": "shortfall", "peer_ratio_72": "shortfall",
    "peer_ratio_168": "shortfall", "peak_ratio_72": "shortfall", "offpeak_ratio_72": "shortfall",
    "shift_ratio": "shortfall", "z_24": "neg", "low_frac_72": "id", "zero_frac_72": "id",
    "corr_72": "decorrelation", "dt_ratio_24": "pos", "dt_z_24": "pos", "dt_ratio_168": "pos", "dt_z_168": "pos",
    "feeder_ratio_24": "pos", "feeder_z_24": "pos", "feeder_ratio_168": "pos",
}
IF_CONSUMER_FEATURES = [f for f in CONSUMER_FEATURES if f in _ONE_SIDED]
IF_COMBINED_FEATURES = [f for f in COMBINED_FEATURES if f in _ONE_SIDED]


def one_sided(X: np.ndarray, names: list[str], keep: list[str]) -> np.ndarray:
    cols = []
    for f in keep:
        x = X[:, names.index(f)]
        kind = _ONE_SIDED[f]
        if kind == "shortfall":
            cols.append(np.maximum(0.0, 1.0 - x))
        elif kind == "neg":
            cols.append(np.maximum(0.0, -x))
        elif kind == "pos":
            cols.append(np.maximum(0.0, x))
        elif kind == "decorrelation":
            cols.append(np.clip((1.0 - x) / 2.0, 0.0, 1.0))
        else:
            cols.append(x)
    return np.column_stack(cols)


def select(X: np.ndarray, names: list[str], keep: list[str]) -> np.ndarray:
    return X[:, [names.index(f) for f in keep]]
