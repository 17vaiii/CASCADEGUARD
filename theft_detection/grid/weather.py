"""Synthetic weather outage overlays for corridor contingency screening."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class WeatherScenario:
    name: str
    description: str
    outage_probability_per_100km: float
    ghat_multiplier: float = 1.0
    source: str = "assumed synthetic scenario"


WEATHER_SCENARIOS = {
    "normal": WeatherScenario("normal", "Baseline weather", 0.002),
    "monsoon_storm": WeatherScenario("monsoon_storm", "Synthetic severe monsoon storm", 0.02, 2.5),
    "heatwave": WeatherScenario("heatwave", "Synthetic high-temperature derating risk", 0.008, 1.4),
}


def line_outage_probabilities(net, scenario: str | WeatherScenario = "normal") -> dict[int, float]:
    """Return per-line synthetic outage priors using section length and region.

    Values are scenario weights for ranking, not calibrated outage rates.
    """
    event = WEATHER_SCENARIOS[scenario] if isinstance(scenario, str) else scenario
    if event.name not in WEATHER_SCENARIOS:
        raise ValueError(f"Unknown weather scenario: {event.name}")
    sections = net.get("section_km", {})
    line_sections = net.get("line_section", {})
    result = {}
    for idx, row in net.line.iterrows():
        section = line_sections.get(int(idx))
        a, b = sections.get(section, (0.0, 100.0)) if section is not None else (0.0, 100.0)
        length = abs(float(b) - float(a))
        midpoint = (float(a) + float(b)) / 2
        multiplier = event.ghat_multiplier if 100 <= midpoint <= 260 else 1.0
        result[int(idx)] = min(0.95, event.outage_probability_per_100km * length / 100 * multiplier)
    return result


def contingency_probability(lines: Iterable[int], probabilities: dict[int, float]) -> float:
    """Independent-trip probability for a contingency, for scenario ranking."""
    probability = 1.0
    for line in lines:
        p = float(probabilities[int(line)])
        if not 0 <= p <= 1:
            raise ValueError("line probabilities must be in [0, 1]")
        probability *= p
    return probability
