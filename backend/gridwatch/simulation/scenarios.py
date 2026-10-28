"""Scenario configuration.

A simulation run is fully determined by a `SimulationConfig` (including its seed).
Scenario types B-G each add one `Injection`; the experiment benchmark uses several
injections per run ("composite"). Scenarios are *defensive research stimuli*: they
alter synthetic numbers in a synthetic dataset and say nothing about how real meters
could be manipulated.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

InjectionType = Literal[
    "sudden_deviation",  # Scenario B
    "unmetered_load",  # Scenario C
    "persistent_anomaly",  # Scenario D
    "missing_delayed",  # Scenario E
    "noise_stress",  # Scenario F
    "loss_estimate_error",  # Scenario G
]

ScenarioCode = Literal["A", "B", "C", "D", "E", "F", "G", "composite"]

SCENARIO_TO_INJECTION: dict[str, InjectionType] = {
    "B": "sudden_deviation",
    "C": "unmetered_load",
    "D": "persistent_anomaly",
    "E": "missing_delayed",
    "F": "noise_stress",
    "G": "loss_estimate_error",
}

# Injection types that represent theft-like (non-technical-loss) behaviour. The others
# are benign stressors used to test false-positive behaviour.
THEFT_LIKE: set[str] = {"sudden_deviation", "unmetered_load", "persistent_anomaly"}

SCENARIO_CATALOG = [
    {
        "code": "A", "name": "Normal operation", "injection": None, "theft_like": False,
        "summary": "Ordinary consumption variation, measurement noise, sparse communication gaps and "
                   "occasional genuine behaviour changes (e.g. vacancy). Nothing is injected.",
        "magnitude": None,
    },
    {
        "code": "B", "name": "Sudden metered-consumption deviation", "injection": "sudden_deviation",
        "theft_like": True,
        "summary": "From the onset, the synthetic *recorded* consumption of selected consumers drops by the "
                   "magnitude while the electrical load they draw is unchanged.",
        "magnitude": {"label": "Recorded-consumption reduction", "unit": "%", "min": 10, "max": 90, "default": 55},
    },
    {
        "code": "C", "name": "Simulated unmetered load", "injection": "unmetered_load", "theft_like": True,
        "summary": "An additional load is attached at a DT's LV network. It flows through the feeder-head and "
                   "DT meters and the power flow, but through no consumer meter.",
        "magnitude": {"label": "Unmetered load (peak) as % of DT average load", "unit": "%", "min": 5, "max": 100,
                      "default": 40},
    },
    {
        "code": "D", "name": "Persistent consumption anomaly", "injection": "persistent_anomaly",
        "theft_like": True,
        "summary": "A gradually developing, persistent under-recording concentrated in each consumer's "
                   "high-consumption hours (ramps in over 72 h).",
        "magnitude": {"label": "Peak-hour recorded-consumption reduction", "unit": "%", "min": 10, "max": 90,
                      "default": 60},
    },
    {
        "code": "E", "name": "Missing or delayed meter readings", "injection": "missing_delayed",
        "theft_like": False,
        "summary": "Communication failures: bursts of missing readings and readings that arrive 6-48 h late. "
                   "Tests whether data-quality problems are mistaken for theft.",
        "magnitude": {"label": "Share of readings lost or delayed", "unit": "%", "min": 5, "max": 90, "default": 50},
    },
    {
        "code": "F", "name": "Measurement-noise stress test", "injection": "noise_stress", "theft_like": False,
        "summary": "Multiplies random error and bias of every meter on the selected feeder.",
        "magnitude": {"label": "Meter-error multiplier", "unit": "x", "min": 1, "max": 20, "default": 8},
    },
    {
        "code": "G", "name": "Technical-loss estimation error", "injection": "loss_estimate_error",
        "theft_like": False,
        "summary": "Perturbs the utility-side technical-loss estimate for the feeder. Negative values "
                   "under-estimate losses and create an apparent unexplained gap.",
        "magnitude": {"label": "Loss-estimate error", "unit": "%", "min": -60, "max": 60, "default": -45},
    },
]


class Injection(BaseModel):
    type: InjectionType
    feeder: str = Field(pattern=r"^F[1-6]$")
    dt: str | None = Field(default=None, pattern=r"^F[1-6]-DT[1-4]$")
    n_consumers: int = Field(default=3, ge=1, le=20)
    magnitude: float
    onset_day: float = Field(default=4.0, ge=0.0, le=13.0)
    duration_days: float = Field(default=8.0, ge=0.5, le=14.0)

    @model_validator(mode="after")
    def _check(self) -> "Injection":
        lim = {
            "sudden_deviation": (10, 90),
            "unmetered_load": (5, 100),
            "persistent_anomaly": (10, 90),
            "missing_delayed": (5, 90),
            "noise_stress": (1, 20),
            "loss_estimate_error": (-60, 60),
        }[self.type]
        if not lim[0] <= self.magnitude <= lim[1]:
            raise ValueError(f"magnitude for {self.type} must be within {lim}")
        if self.dt is not None and not self.dt.startswith(self.feeder + "-"):
            raise ValueError("dt must belong to the selected feeder")
        return self


class SimulationConfig(BaseModel):
    scenario: ScenarioCode = "A"
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    n_feeders: int = Field(default=4, ge=2, le=6)
    dts_per_feeder: int = Field(default=3, ge=2, le=4)
    consumers_per_dt: int = Field(default=25, ge=5, le=80)
    noise_level: float = Field(default=1.0, ge=0.25, le=5.0, description="Global meter-error multiplier")
    base_missing_rate: float = Field(default=0.005, ge=0.0, le=0.2)
    base_delay_rate: float = Field(default=0.02, ge=0.0, le=0.3)
    duplicate_rate: float = Field(default=0.01, ge=0.0, le=0.1)
    benign_change_rate: float = Field(default=0.02, ge=0.0, le=0.2,
                                      description="Share of consumers with a genuine consumption drop")
    outage_rate: float = Field(default=0.3, ge=0.0, le=2.0, description="Supply outages per feeder per week")
    loss_model_error_sd: float = Field(default=0.05, ge=0.0, le=0.3,
                                       description="Background error of the utility loss model (relative SD)")
    systematic_loss_error_pct: float = Field(default=0.0, ge=-60.0, le=60.0,
                                             description="Persistent loss-model error on every feeder, history included "
                                                         "(e.g. wrong conductor data)")
    loss_calibration: bool = Field(default=True, description="Calibrate the technical-loss estimate of each boundary "
                                                             "on the reference (history) period")
    injections: list[Injection] = Field(default_factory=list, max_length=64)
    label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _check(self) -> "SimulationConfig":
        for inj in self.injections:
            if int(inj.feeder[1:]) > self.n_feeders:
                raise ValueError(f"injection feeder {inj.feeder} does not exist (n_feeders={self.n_feeders})")
            if inj.dt is not None and int(inj.dt.split("DT")[1]) > self.dts_per_feeder:
                raise ValueError(f"injection DT {inj.dt} does not exist")
            if inj.n_consumers > self.consumers_per_dt * self.dts_per_feeder:
                raise ValueError("n_consumers exceeds consumers on the feeder")
        if self.scenario == "A" and self.injections:
            raise ValueError("scenario A (normal operation) cannot have injections")
        if self.scenario in SCENARIO_TO_INJECTION:
            want = SCENARIO_TO_INJECTION[self.scenario]
            if len(self.injections) != 1 or self.injections[0].type != want:
                raise ValueError(f"scenario {self.scenario} requires exactly one '{want}' injection")
        return self

    def fingerprint(self) -> str:
        payload = self.model_dump(exclude={"label"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def demo_config() -> SimulationConfig:
    """Pre-configured faculty demonstration: persistent under-recording on feeder F2.

    Disclosure: seed 2043 was *selected* (by scanning seeds 2026-2119) because it shows
    the mechanisms clearly — consumer-level and energy-balance evidence on F2, plus a
    genuine consumption drop on another feeder that the simple rule flags and the
    combined model does not. It is an illustration, not evidence of performance; the
    benchmark results in docs/experiments are the evidence.
    """
    return SimulationConfig(
        scenario="D",
        seed=2043,
        label="Faculty demo: persistent anomaly on F2",
        injections=[Injection(type="persistent_anomaly", feeder="F2", n_consumers=4, magnitude=65,
                              onset_day=5.0, duration_days=9.0)],
    )
