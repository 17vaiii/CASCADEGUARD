"""Randomised composite scenarios for the synthetic benchmark.

Each benchmark run mixes theft-like injections (B, C, D) with benign stressors (E, F, G)
and background effects (genuine consumption drops, outages, communication gaps). Runs
are identified by their seed; train / validation / test use disjoint seed ranges so no
run contributes to more than one split (scenario-grouped split, no leakage).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..simulation.generator import rng_for
from ..simulation.scenarios import Injection, SimulationConfig

PREVALENCE = {"low": 0.01, "medium": 0.03, "high": 0.08}  # share of consumers with recorded-consumption anomalies
UNMETERED_COUNT = {"low": (0, 1), "medium": (1, 1), "high": (2, 2)}

TRAIN_SEEDS = list(range(1000, 1030))
VAL_SEEDS = list(range(2000, 2010))
TEST_SEEDS = list(range(3000, 3030))


@dataclass
class BenchmarkSpec:
    prevalence: str = "medium"
    noise_level: float | None = None  # None = randomised background level
    missing_rate: float | None = None
    loss_error_pct: float = 0.0  # persistent (history included) loss-model error on every feeder
    loss_calibration: bool = True  # calibrate loss estimates on the reference period
    stressors: bool = True
    single_feeder_theft: bool = False  # localisation test: all theft-like events on one feeder
    n_feeders: int = 4
    dts_per_feeder: int = 3
    consumers_per_dt: int = 25


def benchmark_config(seed: int, spec: BenchmarkSpec | None = None) -> SimulationConfig:
    spec = spec or BenchmarkSpec()
    r = rng_for(seed, "benchmark")
    nf, nd = spec.n_feeders, spec.dts_per_feeder
    feeders = [f"F{i + 1}" for i in range(nf)]
    n_consumers = nf * nd * spec.consumers_per_dt
    injections: list[Injection] = []
    theft_feeder = feeders[int(r.integers(0, nf))]

    def pick_feeder() -> str:
        return theft_feeder if spec.single_feeder_theft else feeders[int(r.integers(0, nf))]

    def window() -> tuple[float, float]:
        onset = float(r.uniform(1.0, 9.0))
        return onset, float(min(14.0 - onset, r.uniform(3.0, 13.0)))

    target = max(1, int(round(PREVALENCE[spec.prevalence] * n_consumers)))
    placed = 0
    while placed < target:
        k = int(min(target - placed, r.integers(1, 5)))
        onset, dur = window()
        kind = "sudden_deviation" if r.random() < 0.5 else "persistent_anomaly"
        mag = float(r.uniform(25, 85)) if kind == "sudden_deviation" else float(r.uniform(30, 90))
        injections.append(Injection(type=kind, feeder=pick_feeder(), n_consumers=k, magnitude=round(mag, 1),
                                    onset_day=round(onset, 2), duration_days=round(dur, 2)))
        placed += k
    lo, hi = UNMETERED_COUNT[spec.prevalence]
    for _ in range(int(r.integers(lo, hi + 1))):
        onset, dur = window()
        f = pick_feeder()
        injections.append(Injection(type="unmetered_load", feeder=f, dt=f"{f}-DT{int(r.integers(1, nd + 1))}",
                                    magnitude=round(float(r.uniform(10, 70)), 1), onset_day=round(onset, 2),
                                    duration_days=round(dur, 2)))
    if spec.stressors:
        if r.random() < 0.5:
            onset, dur = window()
            injections.append(Injection(type="missing_delayed", feeder=feeders[int(r.integers(0, nf))],
                                        n_consumers=int(r.integers(2, 7)), magnitude=round(float(r.uniform(20, 80)), 1),
                                        onset_day=round(onset, 2), duration_days=round(dur, 2)))
        if r.random() < 0.3:
            onset, dur = window()
            injections.append(Injection(type="noise_stress", feeder=feeders[int(r.integers(0, nf))],
                                        magnitude=round(float(r.uniform(3, 12)), 1), onset_day=round(onset, 2),
                                        duration_days=round(dur, 2)))
        if r.random() < 0.4:
            onset, dur = window()
            mag = float(r.uniform(15, 50)) * (1 if r.random() < 0.5 else -1)
            injections.append(Injection(type="loss_estimate_error", feeder=feeders[int(r.integers(0, nf))],
                                        magnitude=round(mag, 1), onset_day=round(onset, 2),
                                        duration_days=round(dur, 2)))
    missing = spec.missing_rate if spec.missing_rate is not None else float(r.uniform(0.002, 0.02))
    return SimulationConfig(
        scenario="composite", seed=seed, n_feeders=nf, dts_per_feeder=nd, consumers_per_dt=spec.consumers_per_dt,
        noise_level=spec.noise_level if spec.noise_level is not None else round(float(r.uniform(0.8, 1.3)), 3),
        base_missing_rate=missing, benign_change_rate=round(float(r.uniform(0.02, 0.05)), 3),
        injections=injections, label=f"benchmark seed {seed} ({spec.prevalence})",
        systematic_loss_error_pct=spec.loss_error_pct, loss_calibration=spec.loss_calibration,
    )


def describe_spec(spec: BenchmarkSpec) -> dict:
    return {k: getattr(spec, k) for k in spec.__dataclass_fields__}


def seeds_summary() -> dict:
    return {"train": [TRAIN_SEEDS[0], TRAIN_SEEDS[-1]], "validation": [VAL_SEEDS[0], VAL_SEEDS[-1]],
            "test": [TEST_SEEDS[0], TEST_SEEDS[-1]], "n_train": len(TRAIN_SEEDS), "n_validation": len(VAL_SEEDS),
            "n_test": len(TEST_SEEDS)}
