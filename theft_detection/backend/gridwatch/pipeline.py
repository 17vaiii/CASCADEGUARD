"""Shared pipeline: config -> data -> baseline -> energy accounting -> features.

Used identically by the API, the training code and the experiment scripts.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import pandas as pd

from .config import MODELS_DIR
from .detection.bundle import ModelBundle, train_bundle
from .energy_balance.balance import EnergyAccountant
from .experiments.benchmark import TRAIN_SEEDS, VAL_SEEDS, BenchmarkSpec, benchmark_config
from .features.baseline import Baseline, build_baseline
from .features.build import FeatureBuilder, RuleConfig
from .simulation.generator import SimulationData, generate
from .simulation.scenarios import SimulationConfig

log = logging.getLogger("gridwatch.pipeline")


@dataclass
class RunContext:
    config: SimulationConfig
    data: SimulationData
    baseline: Baseline
    accountant: EnergyAccountant
    features: FeatureBuilder


def prepare(config: SimulationConfig, rules: RuleConfig | None = None) -> RunContext:
    data = generate(config)
    base = build_baseline(data)
    acc = EnergyAccountant(data, base)
    return RunContext(config, data, base, acc, FeatureBuilder(data, base, acc, rules))


def frames_for_seeds(seeds: list[int], spec: BenchmarkSpec | None = None, taus: str = "daily",
                     rules: RuleConfig | None = None) -> dict[str, pd.DataFrame]:
    parts: dict[str, list[pd.DataFrame]] = {"consumer": [], "dt": [], "feeder": []}
    for seed in seeds:
        ctx = prepare(benchmark_config(seed, spec), rules)
        fr = ctx.features.frame(ctx.features.daily_taus() if taus == "daily" else
                                list(range(ctx.data.h0, ctx.data.H)), run_id=str(seed))
        for k in parts:
            parts[k].append(fr[k])
    return {k: pd.concat(v, ignore_index=True) for k, v in parts.items()}


def train_default_bundle(save: bool = True) -> ModelBundle:
    t0 = time.perf_counter()
    log.info("generating %d training and %d validation benchmark runs", len(TRAIN_SEEDS), len(VAL_SEEDS))
    train = frames_for_seeds(TRAIN_SEEDS)
    val = frames_for_seeds(VAL_SEEDS)
    bundle = train_bundle(train, val, meta={"train_seeds": [TRAIN_SEEDS[0], TRAIN_SEEDS[-1]],
                                            "val_seeds": [VAL_SEEDS[0], VAL_SEEDS[-1]],
                                            "benchmark_spec": "BenchmarkSpec() defaults (medium prevalence)"})
    bundle.meta["total_seconds_incl_data"] = round(time.perf_counter() - t0, 1)
    if save:
        path = bundle.save()
        log.info("model bundle saved to %s", path)
    return bundle


def load_or_train_bundle() -> ModelBundle:
    b = ModelBundle.load()
    if b is None:
        log.warning("no usable model bundle in %s - training now (this takes a minute or two)", MODELS_DIR)
        b = train_default_bundle(save=True)
    return b
