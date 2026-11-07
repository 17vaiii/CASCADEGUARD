# OWNER: P4 | STATUS: ACTIVE
"""P4-1: loaders for public benchmark datasets (optional, used when the files are present).

Chosen benchmarks (see ``docs/p4/p4.md`` §7 for the literature scan):

* **SGCC electricity-theft dataset** (State Grid Corporation of China; 42,372 consumers, daily
  kWh 2014-01-01 .. 2016-10-31, binary ``FLAG``). Widely used since Zheng et al., 2018. Used
  for the *supervised comparison* the PRD asks for. Expected file layout: one CSV with columns
  ``CONS_NO``, ``FLAG`` and one column per date.
* **Irish CER / ISSDA smart-meter trial** (30-minute residential and SME data) or
  **London Low Carbon London** smart-meter data, for realistic *base-load behaviour*; theft is
  injected synthetically as in Jokar et al., 2016.

No dataset is downloaded or committed; access terms differ per source. Point the loader at a
local file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_sgcc(path: str | Path, max_consumers: int | None = None) -> tuple[np.ndarray, pd.DatetimeIndex, pd.DataFrame]:
    """Load the SGCC CSV into ``(daily_kwh [C, D], dates, meta)``; ``meta`` has consumer_id, label."""
    df = pd.read_csv(path, nrows=max_consumers)
    if "CONS_NO" not in df.columns or "FLAG" not in df.columns:
        raise ValueError("expected SGCC layout with CONS_NO and FLAG columns")
    date_cols = [c for c in df.columns if c not in ("CONS_NO", "FLAG")]
    dates = pd.to_datetime(pd.Index(date_cols), errors="coerce")
    order = np.argsort(dates.values)
    date_cols = [date_cols[i] for i in order if not pd.isna(dates[i])]
    dates = pd.DatetimeIndex(sorted(d for d in dates if not pd.isna(d)))
    reads = df[date_cols].to_numpy(dtype=float)
    meta = pd.DataFrame({"consumer_id": df.CONS_NO.astype(str), "label": df.FLAG.astype(int)})
    return reads, dates, meta


def daily_features(daily: np.ndarray, history_frac: float = 0.5) -> pd.DataFrame:
    """Daily-resolution subset of the P4 features (no intra-day shape available in SGCC)."""
    x = np.asarray(daily, dtype=float)
    n_d = x.shape[1]
    h = int(n_d * history_frac)
    with np.errstate(invalid="ignore", divide="ignore"):
        hist, rec = np.nanmean(x[:, :h], axis=1), np.nanmean(x[:, h:], axis=1)
        valid = ~np.isnan(x)
        zero = valid & (x < 1e-3)
        roll = pd.DataFrame(x[:, h:]).T.rolling(7, min_periods=3).mean().T.to_numpy()
        out = pd.DataFrame({
            "f_ratio_recent": rec / np.where(hist > 1e-3, hist, np.nan),
            "f_min7_ratio": np.nanmin(roll, axis=1) / np.where(hist > 1e-3, hist, np.nan),
            "f_zero_frac_recent": zero[:, h:].sum(1) / np.maximum(valid[:, h:].sum(1), 1),
            "f_zero_frac_hist": zero[:, :h].sum(1) / np.maximum(valid[:, :h].sum(1), 1),
            "f_missing_frac": 1 - valid.mean(1),
            "f_cv_recent": np.nanstd(x[:, h:], 1) / np.maximum(rec, 1e-3),
            "f_cv_ratio": (np.nanstd(x[:, h:], 1) / np.maximum(rec, 1e-3))
                          / np.maximum(np.nanstd(x[:, :h], 1) / np.maximum(hist, 1e-3), 1e-3),
        })
    return out.replace([np.inf, -np.inf], np.nan)
