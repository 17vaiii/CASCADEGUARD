# OWNER: P3 | STATUS: ACTIVE
"""Calibration and Conformal Prediction for cascade probability and load-loss intervals.

Implements P3-4:
  - Temperature scaling for probability calibration
  - Expected Calibration Error (ECE)
  - Conformal prediction intervals for load loss estimation
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from scipy.optimize import minimize_scalar


def compute_ece(probs: np.ndarray, labels: np.ndarray, num_bins: int = 10) -> float:
    """Compute Expected Calibration Error (ECE).
    
    Args:
      probs: Predicted probabilities in [0, 1].
      labels: Binary true labels {0, 1}.
      num_bins: Number of equal-width probability bins.
    """
    bins = np.linspace(0.0, 1.0, num_bins + 1)
    bin_indices = np.digitize(probs, bins) - 1
    bin_indices = np.clip(bin_indices, 0, num_bins - 1)

    ece = 0.0
    total_samples = len(probs)
    if total_samples == 0:
        return 0.0

    for i in range(num_bins):
        mask = bin_indices == i
        count = np.sum(mask)
        if count > 0:
            avg_conf = np.mean(probs[mask])
            avg_acc = np.mean(labels[mask])
            ece += (count / total_samples) * np.abs(avg_conf - avg_acc)

    return float(ece)


class TemperatureScaler:
    """Optimizes temperature T > 0 on validation logits using Negative Log-Likelihood."""

    def __init__(self):
        self.temperature: float = 1.0

    def fit(self, logits: np.ndarray | torch.Tensor, labels: np.ndarray | torch.Tensor) -> float:
        if isinstance(logits, torch.Tensor):
            logits_np = logits.detach().cpu().numpy().flatten()
        else:
            logits_np = np.asarray(logits, dtype=np.float32).flatten()

        if isinstance(labels, torch.Tensor):
            labels_np = labels.detach().cpu().numpy().flatten()
        else:
            labels_np = np.asarray(labels, dtype=np.float32).flatten()

        def nll(t: float) -> float:
            if t <= 0:
                return 1e9
            scaled_logits = logits_np / t
            # Stable binary cross-entropy: max(x, 0) - x * z + log(1 + exp(-|x|))
            loss = np.maximum(scaled_logits, 0) - scaled_logits * labels_np + np.log(1.0 + np.exp(-np.abs(scaled_logits)))
            return float(np.mean(loss))

        res = minimize_scalar(nll, bounds=(0.05, 10.0), method="bounded")
        self.temperature = float(res.x)
        return self.temperature

    def scale_logits(self, logits: np.ndarray | torch.Tensor) -> np.ndarray:
        t = max(self.temperature, 1e-4)
        if isinstance(logits, torch.Tensor):
            logits_np = logits.detach().cpu().numpy()
        else:
            logits_np = np.asarray(logits, dtype=np.float32)
        return logits_np / t

    def predict_proba(self, logits: np.ndarray | torch.Tensor) -> np.ndarray:
        scaled = self.scale_logits(logits)
        return 1.0 / (1.0 + np.exp(-scaled))


class ConformalIntervalPredictor:
    """Inductive conformal prediction for load loss intervals.
    
    Provides formal finite-sample coverage guarantees at confidence level 1 - alpha.
    """

    def __init__(self, alpha: float = 0.10):
        self.alpha = alpha
        self.q_val: float = 0.0

    def fit(self, y_pred: np.ndarray, y_true: np.ndarray) -> float:
        """Calibrate conformal quantile from validation predictions and ground truth."""
        residuals = np.abs(np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float))
        n = len(residuals)
        if n == 0:
            self.q_val = 0.0
            return 0.0
        
        # Conformal quantile formula: ceiling((n + 1) * (1 - alpha)) / n
        level = min(1.0, np.ceil((n + 1) * (1.0 - self.alpha)) / n)
        self.q_val = float(np.quantile(residuals, level, method="higher"))
        return self.q_val

    def predict_interval(self, y_pred: float | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Compute [lower_bound, upper_bound] for predicted load loss."""
        pred = np.asarray(y_pred, dtype=float)
        lower = np.maximum(0.0, pred - self.q_val)
        upper = pred + self.q_val
        return lower, upper

    def evaluate_coverage(self, y_pred: np.ndarray, y_true: np.ndarray) -> float:
        """Evaluate empirical coverage on test set."""
        lower, upper = self.predict_interval(y_pred)
        covered = (y_true >= lower) & (y_true <= upper)
        return float(np.mean(covered))
