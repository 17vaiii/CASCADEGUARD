"""Test fixtures. Tests use temporary data/model/result directories so they never touch the
application's artefacts, and a small model bundle trained on a few benchmark runs."""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gridwatch-tests-")
os.environ.setdefault("GRIDWATCH_DATA_DIR", os.path.join(_TMP, "data"))
os.environ.setdefault("GRIDWATCH_MODELS_DIR", os.path.join(_TMP, "models"))
os.environ.setdefault("GRIDWATCH_RESULTS_DIR", os.path.join(_TMP, "results"))
os.environ.setdefault("GRIDWATCH_FRONTEND_DIST", os.path.join(_TMP, "no-frontend"))

import pytest  # noqa: E402

from gridwatch.detection.bundle import train_bundle  # noqa: E402
from gridwatch.experiments.benchmark import TRAIN_SEEDS, VAL_SEEDS  # noqa: E402
from gridwatch.pipeline import frames_for_seeds, prepare  # noqa: E402
from gridwatch.simulation.scenarios import Injection, SimulationConfig  # noqa: E402


@pytest.fixture(scope="session")
def small_bundle():
    """A quickly trained bundle (few runs, few trees), saved where the API will load it."""
    train = frames_for_seeds(TRAIN_SEEDS[:3])
    val = frames_for_seeds(VAL_SEEDS[:2])
    bundle = train_bundle(train, val, n_estimators=25)
    bundle.save()
    return bundle


@pytest.fixture(scope="session")
def normal_ctx():
    return prepare(SimulationConfig(scenario="A", seed=11))


@pytest.fixture(scope="session")
def unmetered_ctx():
    return prepare(SimulationConfig(scenario="C", seed=11, injections=[
        Injection(type="unmetered_load", feeder="F3", dt="F3-DT2", magnitude=60, onset_day=3, duration_days=8)]))
