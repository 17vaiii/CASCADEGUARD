"""Reproducible synthetic interval-meter data for Person 4's theft models.

All consumer identifiers are synthetic pseudonyms. Labels describe injected
simulation events and must not be interpreted as real-world findings.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from cascadeguard.common.io import write_parquet

THEFT_TYPES = (
    "meter_bypass", "meter_stop", "night_tapping", "hooking",
    "temporary_tampering",
)
CONSUMER_TYPES = ("residential", "commercial", "small_industrial")


def generate_meter_data(
    output: str | Path = "data/processed/meter_readings.parquet",
    consumers: int = 250,
    days: int = 60,
    interval_minutes: int = 60,
    theft_fraction: float = 0.25,
    seed: int = 42,
) -> pd.DataFrame:
    """Create labelled interval readings and save them as Parquet.

    Each injected consumer has one event interval and a stable ground-truth
    class. Normal consumers use ``theft_type='none'``. Metered consumption and
    unmetered feeder load are separate fields so hooking/tapping never falsify
    meter readings.
    """
    if consumers < 1 or days < 1 or interval_minutes < 1:
        raise ValueError("consumers, days and interval_minutes must be positive")
    if interval_minutes not in (15, 30, 60):
        raise ValueError("interval_minutes must be 15, 30 or 60")
    if not 0 <= theft_fraction <= 1:
        raise ValueError("theft_fraction must be between 0 and 1")

    rng = np.random.default_rng(seed)
    periods = days * 24 * 60 // interval_minutes
    timestamps = pd.date_range("2025-01-01", periods=periods,
                               freq=f"{interval_minutes}min", tz="UTC")
    rows: list[pd.DataFrame] = []
    n_injected = round(consumers * theft_fraction)
    types = np.array(["none"] * (consumers - n_injected) +
                     [THEFT_TYPES[i % len(THEFT_TYPES)] for i in range(n_injected)], dtype=object)
    rng.shuffle(types)
    order = rng.permutation(consumers)
    split_by_consumer = np.empty(consumers, dtype=object)
    n_train, n_val = int(consumers * 0.70), int(consumers * 0.15)
    split_by_consumer[order[:n_train]] = "train"
    split_by_consumer[order[n_train:n_train + n_val]] = "validation"
    split_by_consumer[order[n_train + n_val:]] = "test"
    hour = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60.0
    dow = timestamps.dayofweek.to_numpy()

    for consumer_n, theft_type in enumerate(types):
        ctype = CONSUMER_TYPES[consumer_n % len(CONSUMER_TYPES)]
        feeder_n = consumer_n % max(1, min(20, consumers // 5 or 1))
        typical_kw = {"residential": 1.4, "commercial": 7.5, "small_industrial": 18.0}[ctype]
        customer_scale = float(rng.lognormal(mean=0, sigma=0.25))
        if ctype == "residential":
            daily = 0.58 + 0.24 * np.exp(-((hour - 7.0) / 2.3) ** 2) + 0.55 * np.exp(-((hour - 20.0) / 3.0) ** 2)
        elif ctype == "commercial":
            daily = 0.18 + 0.95 * np.exp(-((hour - 13.0) / 4.2) ** 2)
        else:
            daily = 0.78 + 0.18 * np.exp(-((hour - 14.0) / 6.0) ** 2)
        weekend = np.where(dow >= 5, 0.78 if ctype == "commercial" else 0.92, 1.0)
        seasonal = 1.0 + 0.08 * np.sin(np.arange(periods) / max(periods, 1) * 2 * np.pi)
        base_kwh = np.maximum(0.01, typical_kw * customer_scale * daily * weekend * seasonal
                              * interval_minutes / 60.0)
        base_kwh *= rng.lognormal(mean=-0.5 * 0.08**2, sigma=0.08, size=periods)

        event_start = int(rng.integers(periods // 4, max(periods // 4 + 1, 3 * periods // 4))) if theft_type != "none" else -1
        min_event = max(1, 24 * 60 // interval_minutes)
        event_len = int(rng.integers(min_event, max(min_event + 1, periods // 4))) if theft_type != "none" else 0
        event_end = min(periods, event_start + event_len) if event_start >= 0 else -1
        active = np.zeros(periods, dtype=bool)
        if event_start >= 0:
            active[event_start:event_end] = True

        meter = base_kwh.copy()
        hidden_kwh = np.zeros(periods, dtype=float)
        tamper_event = np.zeros(periods, dtype=bool)
        if theft_type == "meter_bypass":
            meter[active] *= float(rng.uniform(0.25, 0.65))
        elif theft_type == "meter_stop":
            meter[active] = 0.0
        elif theft_type == "night_tapping":
            night = (hour <= 5.5) | (hour >= 22.0)
            hidden_kwh[active & night] = base_kwh[active & night] * float(rng.uniform(0.2, 0.8))
        elif theft_type == "hooking":
            # Extra demand appears in the feeder balance, not on a consumer meter.
            hidden_kwh[active] = float(rng.uniform(0.4, 4.0)) * interval_minutes / 60.0
        elif theft_type == "temporary_tampering":
            tamper_event[active] = rng.random(active.sum()) < 0.65
            meter[active] = np.where(tamper_event[active], meter[active] * rng.uniform(0.0, 0.35), meter[active])

        rows.append(pd.DataFrame({
            "timestamp": timestamps,
            "consumer_id": f"C{consumer_n:07d}",
            "feeder_id": f"F{feeder_n:03d}",
            "consumer_type": ctype,
            "metered_kwh": np.round(meter, 5),
            "feeder_unmetered_kwh": np.round(hidden_kwh, 5),
            "is_event": active,
            "is_suspected_loss": (active & ((meter < base_kwh * 0.95) | (hidden_kwh > 0))),
            "theft_type": theft_type,
            "event_start": timestamps[event_start] if event_start >= 0 else pd.NaT,
            "event_end": timestamps[event_end - 1] if event_end > event_start else pd.NaT,
            "tamper_event": tamper_event,
            "scenario_seed": seed,
            "split": split_by_consumer[consumer_n],
        }))

    frame = pd.concat(rows, ignore_index=True)
    write_parquet(frame, output)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/processed/meter_readings.parquet")
    parser.add_argument("--consumers", type=int, default=250)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--interval-minutes", type=int, choices=(15, 30, 60), default=60)
    parser.add_argument("--theft-fraction", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    frame = generate_meter_data(args.output, args.consumers, args.days,
                                args.interval_minutes, args.theft_fraction, args.seed)
    print(f"Wrote {len(frame):,} interval records to {args.output}")
    print(frame.groupby("theft_type", observed=True).agg(consumers=("consumer_id", "nunique"), rows=("consumer_id", "size")).to_string())


if __name__ == "__main__":
    main()
