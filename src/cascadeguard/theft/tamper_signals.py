# OWNER: P4 | STATUS: ACTIVE
"""T7 / P4-9: smart-meter tamper-event signals.

Meter event logs (cover open, magnetic interference, reverse current, power-off) are turned
into per-consumer features. Raw counts are weak evidence on their own: meters raise spurious
alarms, and rooftop-solar export legitimately triggers reverse-current events. The features
therefore separate the reference (history) period from the scoring window and are only used
in combination with consumption evidence (fusion, T4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EVENT_TYPES = ("cover_open", "magnetic_interference", "reverse_current", "power_off")


def tamper_features(tamper_log: pd.DataFrame | None, consumer_ids: pd.Series | list[str],
                    history_end: int, n_periods: int, interval_hours: float = 1.0) -> pd.DataFrame:
    """Per-consumer tamper features indexed by ``consumer_id``.

    Columns: ``f_tamper_<type>_recent`` counts, ``f_tamper_total_recent``,
    ``f_tamper_rate_change`` (events/day, recent minus history) and
    ``f_tamper_strong_recent`` (cover-open + magnetic, the types least explained by solar).
    """
    out = pd.DataFrame(index=pd.Index(list(consumer_ids), name="consumer_id"))
    log = tamper_log if tamper_log is not None and len(tamper_log) else \
        pd.DataFrame({"consumer_id": pd.Series(dtype=str), "t_idx": pd.Series(dtype=int),
                      "event_type": pd.Series(dtype=str)})
    recent = log[log.t_idx >= history_end]
    hist = log[log.t_idx < history_end]
    for ev in EVENT_TYPES:
        out[f"f_tamper_{ev}_recent"] = (recent[recent.event_type == ev].groupby("consumer_id").size()
                                        .reindex(out.index).fillna(0).astype(float))
    out["f_tamper_total_recent"] = out[[f"f_tamper_{e}_recent" for e in EVENT_TYPES]].sum(axis=1)
    per_day = 24.0 / interval_hours
    hist_days = max(history_end, 1) / per_day
    recent_days = max(n_periods - history_end, 1) / per_day
    hist_rate = hist.groupby("consumer_id").size().reindex(out.index).fillna(0) / hist_days
    out["f_tamper_rate_change"] = out.f_tamper_total_recent / recent_days - hist_rate
    out["f_tamper_strong_recent"] = out.f_tamper_cover_open_recent + out.f_tamper_magnetic_interference_recent
    return out


def tamper_summary(tamper_log: pd.DataFrame, consumer_id: str, history_end: int) -> dict[str, int]:
    """Counts by event type in the scoring window for one consumer (used in reason codes)."""
    rows = tamper_log[(tamper_log.consumer_id == consumer_id) & (tamper_log.t_idx >= history_end)]
    return {str(k): int(v) for k, v in rows.event_type.value_counts().items()} if len(rows) else {}


def tamper_only_score(features: pd.DataFrame) -> np.ndarray:
    """Rule baseline: weight strong tamper types above ambiguous ones."""
    return (2.0 * features.f_tamper_strong_recent + features.f_tamper_power_off_recent
            + 0.5 * features.f_tamper_reverse_current_recent).to_numpy(dtype=float)
