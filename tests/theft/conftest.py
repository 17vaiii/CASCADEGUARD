# OWNER: P4 | STATUS: ACTIVE
"""Shared small-scale fixtures for P4 tests (kept small so the suite runs in about a minute)."""

from __future__ import annotations

import warnings

import pytest

from cascadeguard.theft import load_config

warnings.filterwarnings("ignore")


def small_config() -> dict:
    cfg = load_config()
    cfg["simulation"]["days"] = 28
    cfg["simulation"]["history_days"] = 14
    cfg["simulation"]["theft_fraction"] = 0.08
    cfg["feeder_electrical"]["fit_scales"] = [0.2, 0.6, 1.0, 1.4]
    cfg["models"]["isolation_forest"]["n_estimators"] = 60
    cfg["models"]["autoencoder"]["max_iter"] = 200
    cfg["models"]["gbm"]["max_iter"] = 60
    cfg["models"]["cv_folds"] = 3
    cfg["graph"]["epochs"] = 40
    cfg["inspection"]["capacity_k"] = 15
    return cfg


@pytest.fixture(scope="session")
def cfg() -> dict:
    return small_config()


@pytest.fixture(scope="session")
def ds(cfg):
    from cascadeguard.theft.feeder_sim import simulate_distribution
    return simulate_distribution(cfg, seed=7, scale=0.3)


@pytest.fixture(scope="session")
def balances(ds, cfg):
    from cascadeguard.theft import energy_balance as eb
    return eb.feeder_balance(ds, cfg["energy_balance"]["flag_z"]), eb.dt_balance(ds, cfg["energy_balance"]["flag_z"])


@pytest.fixture(scope="session")
def features(ds, balances, cfg):
    from cascadeguard.theft.pipeline import build_feature_table
    fb, db = balances
    return build_feature_table(ds, fb, db, cfg)
