# OWNER: P4 | STATUS: ACTIVE
"""T5 / P4-7: human-readable reason codes for every inspection lead.

Each code is derived from an interpretable feature with a stated threshold, so a field crew can
see *why* a lead was raised, and also *what argues against it* (mitigating codes such as a
rooftop-solar pattern or missing reads). Wording always says "suspected"; a lead is never a
finding of theft.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _pct(x: float) -> str:
    return f"{abs(100.0 * x):.0f}%"


def consumer_reason_codes(f: pd.Series, tamper: dict[str, int] | None = None,
                          feeder_id: str | None = None, dt_id: str | None = None) -> list[dict[str, Any]]:
    """Reason codes for one consumer from its feature row (``f_*`` columns)."""
    g = lambda k, d=np.nan: f.get(k, d)  # noqa: E731
    codes: list[dict[str, Any]] = []

    def add(code: str, text: str, weight: float, kind: str = "supporting") -> None:
        codes.append({"code": code, "text": text, "weight": round(float(weight), 3), "kind": kind})

    ratio = g("f_min7_ratio")
    if pd.notna(ratio) and ratio < 0.7:
        add("CONSUMPTION_DROP", f"Consumption fell {_pct(1 - ratio)} below this consumer's own history "
            "(lowest 7-day average in the scoring window).", 1 - ratio)
    step = g("f_step_drop", 0.0)
    if pd.notna(step) and step > 0.3:
        add("STEP_CHANGE", f"Sudden sustained step drop of {_pct(step)} rather than a gradual change.", step)
    peer_ratio = g("f_peer_ratio")
    peer_z = g("f_peer_z")
    own = g("f_ratio_recent")
    if pd.notna(peer_z) and peer_z < -2.5 and pd.notna(peer_ratio) and peer_ratio > 0:
        peer_change = own / peer_ratio - 1.0
        add("PEER_DIVERGENCE", f"Peers of the same type on the same feeder changed by {100 * peer_change:+.0f}% "
            f"while this consumer changed by {100 * (own - 1):+.0f}%.", min(abs(peer_z) / 5, 1.5))
    zf, zh = g("f_zero_frac_recent", 0.0), g("f_zero_frac_hist", 0.0)
    if pd.notna(zf) and zf > 0.15 and zf > 2 * (zh or 0):
        add("ZERO_READS", f"Zero readings in {_pct(zf)} of intervals (longest run "
            f"{g('f_zero_run_days', 0):.1f} days) versus {_pct(zh or 0)} in the reference period.", zf)
    night = g("f_night_share_change", 0.0)
    if pd.notna(night) and abs(night) > 0.1:
        add("NIGHT_PATTERN", f"Night-time share of consumption shifted by {100 * night:+.0f} points.", abs(night))
    fz = g("f_feeder_z", 0.0)
    if pd.notna(fz) and fz >= 3:
        add("FEEDER_RESIDUAL", f"Feeder {feeder_id or ''} unexplained loss rose by "
            f"{g('f_feeder_change_pct', 0):.1f}% of input in the same window (z = {fz:.0f}).".replace("  ", " "),
            min(np.log1p(fz) / 3, 1.5))
    dz = g("f_dt_z", np.nan)
    if pd.notna(dz) and dz >= 3:
        add("DT_RESIDUAL", f"Transformer {dt_id or ''} unexplained loss rose by "
            f"{g('f_dt_change_pct', 0):.1f}% of its input (z = {dz:.0f}).".replace("  ", " "),
            min(np.log1p(dz) / 3, 1.5))
    if tamper:
        strong = tamper.get("cover_open", 0) + tamper.get("magnetic_interference", 0)
        if strong or tamper.get("power_off", 0):
            parts = ", ".join(f"{k.replace('_', ' ')} x{v}" for k, v in sorted(tamper.items()))
            add("TAMPER_EVENTS", f"Meter tamper events in the scoring window: {parts}.", 0.3 + 0.2 * strong)

    # Mitigating evidence (pushes towards a legitimate explanation).
    solar = g("f_solar_signature", 0.0)
    if pd.notna(solar) and solar > 0.3 and g("f_day_ratio", 1.0) < 0.75:
        add("SOLAR_LIKE", "Drop is concentrated in daytime hours with night use unchanged, which is "
            "consistent with rooftop solar (legitimate).", -solar, "mitigating")
    missing = g("f_missing_frac", 0.0)
    if pd.notna(missing) and missing > 0.03:
        add("MISSING_READS", f"{_pct(missing)} of reads are missing; check meter communication first.",
            -missing * 3, "mitigating")
    if pd.notna(fz) and fz < 1.0 and (pd.isna(dz) or dz < 1.0):
        add("NETWORK_BALANCED", "No rise in unexplained loss on the feeder or transformer; a meter drop "
            "here may be a legitimate change (vacancy, efficiency).", -0.5, "mitigating")
    codes.sort(key=lambda c: -c["weight"])
    return codes


def network_reason_codes(node_id: str, level: str, summary_row: pd.Series,
                         explained_kwh: float = 0.0) -> list[dict[str, Any]]:
    """Reason codes for a DT / feeder lead (suspected hooking or direct tapping)."""
    return [{
        "code": f"{level.upper()}_UNEXPLAINED_LOSS",
        "text": (f"{level.upper()} {node_id}: unexplained loss rose from {summary_row.hist_pct:.1f}% to "
                 f"{summary_row.recent_pct:.1f}% of input (7-day peak {summary_row.peak7_pct:.1f}%, "
                 f"z = {summary_row.z:.0f}); {explained_kwh:,.0f} kWh is explained by consumer leads below it."),
        "weight": float(np.log1p(max(summary_row.z, 0))), "kind": "supporting",
    }, {
        "code": "PATROL_FOR_UNMETERED_LOAD",
        "text": "Consumer meters below this node do not account for the residual: patrol the lines "
                "for hooks / direct taps and audit service connections.",
        "weight": 0.5, "kind": "supporting",
    }]


def summary_sentence(codes: list[dict[str, Any]], prob: float, confidence: str) -> str:
    support = [c for c in codes if c["kind"] == "supporting"][:2]
    against = [c for c in codes if c["kind"] == "mitigating"][:1]
    text = f"Suspected non-technical loss (score {prob:.0%}, {confidence} confidence)"
    if support:
        text += ": " + "; ".join(c["text"].rstrip(".") for c in support)
    if against:
        text += ". Note: " + against[0]["text"].rstrip(".")
    return text + ". Requires field verification."
