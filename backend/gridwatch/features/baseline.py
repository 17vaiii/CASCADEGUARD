"""Expected-consumption baseline learned from the clean history period.

For every consumer the baseline is the mean reading per (day type, hour of day), where
day type is weekday / Saturday / Sunday. Saturday and Sunday have only four samples in a
28-day history, so their profiles are shrunk halfway toward the weekday shape scaled to
the day type's own daily total. Hours with a known supply outage (feeder-head meter reads
zero) and readings that had not arrived by the end of the history are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..simulation.generator import SimulationData


@dataclass
class Baseline:
    expected_kwh: np.ndarray  # [C, H]
    expected_sd: np.ndarray  # [C, H]
    peak_mask: np.ndarray  # [C, H] True where the expected value is above the consumer's median
    outage_known: np.ndarray  # [n_f, H] outage visible to the utility (feeder meter reads 0)


def day_type(dow: np.ndarray) -> np.ndarray:
    return np.where(dow == 5, 1, np.where(dow == 6, 2, 0))


def build_baseline(d: SimulationData) -> Baseline:
    C = len(d.consumer_ids)
    h0 = d.h0
    n_hist_days = h0 // 24
    outage_known = d.feeder_meter_kwh == 0.0
    hist = d.meter_kwh[:, :h0].copy()
    hrs = np.arange(h0)
    arrived = hrs[None, :] + d.arrival_delay[:, :h0] < h0
    hist[~arrived] = np.nan
    hist[outage_known[d.consumer_feeder_idx][:, :h0]] = np.nan
    hist = hist.reshape(C, n_hist_days, 24)
    dtypes = day_type(d.dow[: h0 : 24])
    prof = np.empty((C, 3, 24))
    for t in range(3):
        prof[:, t] = np.nanmean(hist[:, dtypes == t], axis=1)
    wk = prof[:, 0]
    wk_total = np.nansum(wk, axis=1, keepdims=True)
    for t in (1, 2):
        own_total = np.nansum(prof[:, t], axis=1, keepdims=True)
        scaled = wk * own_total / np.maximum(wk_total, 1e-9)
        prof[:, t] = 0.5 * prof[:, t] + 0.5 * scaled
    prof = np.nan_to_num(prof, nan=0.0)
    resid = hist - prof[:, dtypes]
    sd_hod = np.nanstd(resid, axis=1)  # [C, 24]
    sd_hod = np.where(np.isfinite(sd_hod), sd_hod, 0.0)
    # Floor the SD so a consumer with a very flat history does not get near-zero uncertainty.
    sd_hod = np.maximum(sd_hod, 0.05 * np.maximum(prof.mean(axis=1), 1e-3))

    all_dt = day_type(d.dow)
    expected = prof[:, all_dt, d.hod]
    expected_sd = sd_hod[:, d.hod]
    med = np.median(prof[:, 0], axis=1, keepdims=True)
    peak_mask = expected >= med
    return Baseline(expected_kwh=expected, expected_sd=expected_sd, peak_mask=peak_mask, outage_known=outage_known)
