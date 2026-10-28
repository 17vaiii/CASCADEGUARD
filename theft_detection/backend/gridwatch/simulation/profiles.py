"""Stylised hourly load-shape templates (synthetic assumptions, not measured data).

Each template is a 24-value shape with mean 1.0, so that a consumer's daily energy is
`daily_kwh = mean_kw * 24`. Shapes encode qualitative knowledge only: residential
double peaks, commercial daytime plateaus and single-shift industrial operation.
"""

from __future__ import annotations

import numpy as np

CATEGORIES = ("residential", "commercial", "industrial")

_RES_WEEKDAY = [0.55, 0.48, 0.45, 0.45, 0.50, 0.75, 1.30, 1.55, 1.35, 1.00, 0.85, 0.80,
                0.82, 0.80, 0.78, 0.80, 0.90, 1.15, 1.60, 1.85, 1.90, 1.70, 1.25, 0.80]
_RES_WEEKEND = [0.60, 0.50, 0.47, 0.45, 0.47, 0.55, 0.85, 1.15, 1.35, 1.35, 1.20, 1.10,
                1.10, 1.05, 1.00, 0.98, 1.00, 1.15, 1.50, 1.75, 1.80, 1.60, 1.25, 0.85]
_COM_DAY = [0.25, 0.22, 0.22, 0.22, 0.24, 0.30, 0.45, 0.70, 1.10, 1.50, 1.65, 1.70,
            1.65, 1.60, 1.65, 1.65, 1.65, 1.70, 1.75, 1.65, 1.35, 0.85, 0.45, 0.30]
_IND_DAY = [0.35, 0.33, 0.33, 0.33, 0.35, 0.40, 0.60, 1.10, 1.75, 1.85, 1.85, 1.80,
            1.45, 1.75, 1.85, 1.85, 1.80, 1.70, 1.30, 0.80, 0.50, 0.40, 0.37, 0.35]

# Day-of-week energy multipliers, Monday=0 ... Sunday=6.
DOW_FACTOR = {
    "residential": np.array([1.00, 1.00, 1.00, 1.00, 1.00, 1.06, 1.10]),
    "commercial": np.array([1.00, 1.00, 1.00, 1.00, 1.02, 0.92, 0.60]),
    "industrial": np.array([1.00, 1.00, 1.00, 1.00, 1.00, 0.85, 0.35]),
}

# Lognormal median daily energy (kWh/day) and dispersion per category (assumptions
# chosen to resemble urban Indian LT consumers in order of magnitude only).
DAILY_KWH_MEDIAN = {"residential": 7.0, "commercial": 35.0, "industrial": 200.0}
DAILY_KWH_SIGMA = {"residential": 0.45, "commercial": 0.55, "industrial": 0.55}

# Hourly multiplicative noise (lognormal sigma) and day-to-day AR(1) variation.
HOURLY_SIGMA = {"residential": 0.28, "commercial": 0.16, "industrial": 0.13}
DAILY_SIGMA = {"residential": 0.10, "commercial": 0.07, "industrial": 0.08}
WEATHER_SENSITIVITY = {"residential": 1.0, "commercial": 0.8, "industrial": 0.3}

# Assumed power factors, used only to give the power-flow model a reactive component.
POWER_FACTOR = {"residential": 0.95, "commercial": 0.92, "industrial": 0.88}

CATEGORY_MIX = {
    "industrial": (0.35, 0.25, 0.40),
    "mixed": (0.55, 0.35, 0.10),
    "residential": (0.85, 0.13, 0.02),
}


def _norm(v: list[float]) -> np.ndarray:
    a = np.asarray(v, dtype=float)
    return a / a.mean()


def shape(category: str, weekend: bool) -> np.ndarray:
    if category == "residential":
        return _norm(_RES_WEEKEND if weekend else _RES_WEEKDAY)
    if category == "commercial":
        return _norm(_COM_DAY)
    return _norm(_IND_DAY)


def unmetered_shape() -> np.ndarray:
    """Profile used for a simulated unmetered load: evening-weighted with a base."""
    s = 0.5 + 0.5 * _norm(_RES_WEEKDAY) / _norm(_RES_WEEKDAY).max()
    return s / s.max()  # peak = 1.0 so the magnitude parameter is a peak value


def hydro_dispatch_mw(hour_of_day: int) -> float:
    """Illustrative peaking-hydro dispatch for the generator node (not real SGS data)."""
    base = 330.0
    evening = 260.0 * np.exp(-0.5 * ((hour_of_day - 19.5) / 2.2) ** 2)
    morning = 110.0 * np.exp(-0.5 * ((hour_of_day - 8.5) / 1.8) ** 2)
    return float(base + evening + morning)


def other_66kv_load_mw(hour_of_day: int, dow: int) -> float:
    """Illustrative aggregate load of the receiving station's unmodelled 66 kV substations."""
    s = _norm(_RES_WEEKDAY) * 0.45 + _norm(_COM_DAY) * 0.30 + _norm(_IND_DAY) * 0.25
    weekly = 0.9 if dow == 6 else 1.0
    return float(85.0 * s[hour_of_day] * weekly)
