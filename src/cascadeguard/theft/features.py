# OWNER: P4 | NEEDS: P2 | STATUS: ACTIVE
"""T3: consumer-level features from interval meter reads.

Every feature compares the **scoring window** (after ``history_end``) with the consumer's own
**reference period** (before it) and with **peers** (same feeder and consumer type), so normal
seasonal drift and shared events (heat, holidays) cancel out. Missing reads (NaN) are excluded,
not treated as zero, and their share is a separate feature (communication gaps are a known
look-alike of meter stoppage).

Works on any ``[n_consumers, n_periods]`` read matrix, e.g. the P4 simulator or P2's
``meter_readings.parquet`` (see :func:`reads_from_meter_frame`).
"""

from __future__ import annotations

from typing import Any
import warnings

import numpy as np
import pandas as pd

from cascadeguard.theft import load_config

ZERO_KWH = 1e-3


def reads_from_meter_frame(frame: pd.DataFrame) -> tuple[np.ndarray, pd.DatetimeIndex, pd.DataFrame]:
    """Pivot a long P2 meter frame (``contracts/meter_data.schema.json``) to a read matrix."""
    wide = frame.pivot_table(index="consumer_id", columns="timestamp", values="metered_kwh", aggfunc="sum")
    meta = (frame.drop_duplicates("consumer_id").set_index("consumer_id")
            .reindex(wide.index)[["feeder_id", "consumer_type"]].reset_index())
    return wide.to_numpy(dtype=np.float64), pd.DatetimeIndex(wide.columns), meta


def _rolling_mean(daily: np.ndarray, window: int) -> np.ndarray:
    """NaN-aware trailing rolling mean over the day axis of [C, D]."""
    valid = ~np.isnan(daily)
    vals = np.where(valid, daily, 0.0)
    cs = np.cumsum(np.pad(vals, ((0, 0), (1, 0))), axis=1)
    cn = np.cumsum(np.pad(valid.astype(float), ((0, 0), (1, 0))), axis=1)
    s = cs[:, window:] - cs[:, :-window]
    n = cn[:, window:] - cn[:, :-window]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n >= max(2, window // 2), s / np.maximum(n, 1), np.nan)


def _max_run(mask: np.ndarray) -> np.ndarray:
    """Longest run of True per row."""
    out = np.zeros(mask.shape[0])
    run = np.zeros(mask.shape[0])
    for t in range(mask.shape[1]):
        run = np.where(mask[:, t], run + 1, 0)
        out = np.maximum(out, run)
    return out


def _row_corr(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, message="Mean of empty slice")
        with np.errstate(all="ignore"):
            a = a - np.nanmean(a, axis=1, keepdims=True)
            b = b - np.nanmean(b, axis=1, keepdims=True)
    num = np.nansum(a * b, axis=1)
    den = np.sqrt(np.nansum(a**2, axis=1) * np.nansum(b**2, axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 1e-12, num / den, 0.0)


def consumer_features(reads: np.ndarray, timestamps: pd.DatetimeIndex, history_end: int,
                      meta: pd.DataFrame, config: dict[str, Any] | None = None) -> pd.DataFrame:
    """Build the feature table (one row per consumer, ``f_*`` columns, indexed by consumer_id).

    ``meta`` needs ``consumer_id``, ``feeder_id`` and ``consumer_type`` in the same row order
    as ``reads``. Labels are never read.
    """
    cfg = (config or load_config())["features"]
    x = np.asarray(reads, dtype=np.float64)
    n_c, n_t = x.shape
    step_h = (timestamps[1] - timestamps[0]).total_seconds() / 3600.0 if n_t > 1 else 1.0
    per_day = int(round(24 / step_h))
    n_days = n_t // per_day
    hist_days = history_end // per_day
    x = x[:, :n_days * per_day]
    hour = (timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60.0)[:n_days * per_day]
    h, r = slice(0, hist_days * per_day), slice(hist_days * per_day, None)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, message="Mean of empty slice")
        with np.errstate(all="ignore"):
            hist_mean = np.nanmean(x[:, h], axis=1)
            recent_mean = np.nanmean(x[:, r], axis=1)
            safe_hist = np.where(hist_mean > ZERO_KWH, hist_mean, np.nan)
            f = pd.DataFrame(index=pd.Index(meta.consumer_id.to_numpy(), name="consumer_id"))
            f["f_hist_mean_kwh"] = hist_mean
            f["f_recent_mean_kwh"] = recent_mean
            f["f_ratio_recent"] = recent_mean / safe_hist

            daily = x.reshape(n_c, n_days, per_day)
            daily_valid = (~np.isnan(daily)).sum(axis=2)
            daily_mean = np.where(daily_valid > per_day // 2, np.nanmean(daily, axis=2), np.nan)
        roll = _rolling_mean(daily_mean, int(cfg["rolling_days"]))
        first_recent = max(0, hist_days - int(cfg["rolling_days"]) + 1)
        f["f_min7_ratio"] = np.nanmin(roll[:, first_recent:], axis=1) / safe_hist

        # Best single change-point drop over the scoring window (relative to the level before it).
        cs = np.nancumsum(daily_mean, axis=1)
        cn = np.cumsum(~np.isnan(daily_mean), axis=1)
        best = np.full(n_c, -np.inf)
        for k in range(max(hist_days, 3), n_days - 2):
            before = cs[:, k - 1] / np.maximum(cn[:, k - 1], 1)
            after = (cs[:, -1] - cs[:, k - 1]) / np.maximum(cn[:, -1] - cn[:, k - 1], 1)
            best = np.maximum(best, (before - after) / np.maximum(before, ZERO_KWH))
        f["f_step_drop"] = np.where(np.isfinite(best), best, 0.0)

        valid = ~np.isnan(x)
        zero = valid & (x < ZERO_KWH)
        f["f_zero_frac_recent"] = zero[:, r].sum(1) / np.maximum(valid[:, r].sum(1), 1)
        f["f_zero_frac_hist"] = zero[:, h].sum(1) / np.maximum(valid[:, h].sum(1), 1)
        f["f_zero_run_days"] = _max_run(zero[:, r]) / per_day
        f["f_missing_frac"] = 1.0 - valid.mean(axis=1)

        lo, hi = cfg["night_hours"]
        night = (hour >= lo) | (hour < hi + 1)
        d_lo, d_hi = cfg["day_hours"]
        day = (hour >= d_lo) & (hour <= d_hi)

        def share(mask: np.ndarray, sl: slice) -> np.ndarray:
            part = np.nansum(np.where(mask[sl], x[:, sl], 0.0), axis=1)
            return part / np.maximum(np.nansum(x[:, sl], axis=1), ZERO_KWH)

        def window_mean(mask: np.ndarray, sl: slice) -> np.ndarray:
            return np.nanmean(np.where(mask[sl], x[:, sl], np.nan), axis=1)

        f["f_night_share_change"] = share(night, r) - share(night, h)
        f["f_day_ratio"] = window_mean(day, r) / np.where(window_mean(day, h) > ZERO_KWH, window_mean(day, h), np.nan)
        offday = ~day
        f["f_offday_ratio"] = window_mean(offday, r) / np.where(window_mean(offday, h) > ZERO_KWH,
                                                                 window_mean(offday, h), np.nan)
        f["f_solar_signature"] = f.f_offday_ratio - f.f_day_ratio   # large & positive -> solar-like

        prof_h = np.nanmean(daily[:, :hist_days], axis=1)
        prof_r = np.nanmean(daily[:, hist_days:], axis=1)
        f["f_profile_corr"] = _row_corr(prof_h, prof_r)

        d_hist, d_rec = daily_mean[:, :hist_days], daily_mean[:, hist_days:]
        cv_h = np.nanstd(d_hist, axis=1) / np.maximum(np.nanmean(d_hist, axis=1), ZERO_KWH)
        cv_r = np.nanstd(d_rec, axis=1) / np.maximum(np.nanmean(d_rec, axis=1), ZERO_KWH)
        f["f_cv_recent"] = cv_r
        f["f_cv_ratio"] = cv_r / np.maximum(cv_h, 1e-3)

    # Peer comparison: same feeder and type (fallback: same type overall).
    group = meta.feeder_id.astype(str).to_numpy() + "|" + meta.consumer_type.astype(str).to_numpy()
    ratio = f.f_ratio_recent.to_numpy()
    peer_med = np.full(n_c, np.nan)
    peer_mad = np.full(n_c, np.nan)
    peer_daily = np.full((n_c, n_days - hist_days), np.nan)
    for keys in (group, meta.consumer_type.astype(str).to_numpy()):
        for g in np.unique(keys):
            idx = np.where(keys == g)[0]
            todo = idx[np.isnan(peer_med[idx])]
            if len(idx) < 4 or len(todo) == 0:
                continue
            vals = ratio[idx]
            med = np.nanmedian(vals)
            mad = np.nanmedian(np.abs(vals - med)) * 1.4826
            peer_med[todo], peer_mad[todo] = med, max(mad, 0.05)
            norm = d_rec[idx] / np.maximum(np.nanmean(d_hist[idx], axis=1, keepdims=True), ZERO_KWH)
            peer_daily[todo] = np.nanmedian(norm, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        f["f_peer_ratio"] = ratio / peer_med
        f["f_peer_z"] = (ratio - peer_med) / peer_mad
        own_norm = d_rec / np.maximum(np.nanmean(d_hist, axis=1, keepdims=True), ZERO_KWH)
        f["f_peer_daily_corr"] = _row_corr(own_norm, peer_daily)
    return f.replace([np.inf, -np.inf], np.nan)


def context_features(consumers: pd.DataFrame, feeder_summary: pd.DataFrame,
                     dt_summary: pd.DataFrame | None) -> pd.DataFrame:
    """Network context from the T2 energy balance, mapped onto every consumer below a node.

    A high feeder / DT residual raises the prior for every consumer below it (PRD §7.1).
    Unmetered DTs get NaN (the models handle missing values) plus ``f_dt_metered = 0``.
    """
    fs = feeder_summary.set_index("node_id")
    out = pd.DataFrame(index=pd.Index(consumers.consumer_id.to_numpy(), name="consumer_id"))
    out["f_feeder_z"] = fs.z.reindex(consumers.feeder_id).to_numpy()
    out["f_feeder_change_pct"] = fs.peak_change_pct.reindex(consumers.feeder_id).to_numpy()
    if dt_summary is not None and len(dt_summary):
        ds_ = dt_summary.set_index("node_id")
        out["f_dt_z"] = ds_.z.reindex(consumers.dt_id).to_numpy()
        out["f_dt_change_pct"] = ds_.peak_change_pct.reindex(consumers.dt_id).to_numpy()
        out["f_dt_metered"] = consumers.dt_id.isin(ds_.index).astype(float).to_numpy()
    else:
        out["f_dt_z"] = np.nan
        out["f_dt_change_pct"] = np.nan
        out["f_dt_metered"] = 0.0
    return out


BEHAVIOUR_COLUMNS = [
    "f_ratio_recent", "f_min7_ratio", "f_step_drop", "f_zero_frac_recent", "f_zero_frac_hist",
    "f_zero_run_days", "f_missing_frac", "f_night_share_change", "f_day_ratio", "f_offday_ratio",
    "f_solar_signature", "f_profile_corr", "f_cv_recent", "f_cv_ratio", "f_peer_ratio", "f_peer_z",
    "f_peer_daily_corr",
]
