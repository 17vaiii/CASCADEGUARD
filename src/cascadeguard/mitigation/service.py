# OWNER: P5 | NEEDS: P2 | STATUS: ACTIVE
"""Request handler behind ``POST /api/mitigate`` (and reusable by any client)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from cascadeguard.mitigation import ADVISORY
from cascadeguard.mitigation.network import Event, OperatingState, build_state
from cascadeguard.mitigation.verifier import describe_actions, mitigate

SEASONS = ("monsoon", "post_monsoon", "summer")


@lru_cache(maxsize=12)
def _state(season: str, theft_aware: bool, intensity: float) -> OperatingState:
    hidden = None
    if theft_aware:
        from cascadeguard.dashboard.data import hidden_load_vector
        hidden = hidden_load_vector(season, intensity)
        if hidden is None:
            raise ValueError("theft_aware requires the P4 pipeline outputs (ntl_ratio_by_substation.parquet)")
    return build_state(season, hidden, label="aware" if hidden else "scada")


def mitigation_request(snapshot: dict[str, Any], with_brief: bool = False) -> dict[str, Any]:
    season = str(snapshot["season"])
    if season not in SEASONS:
        raise ValueError(f"season must be one of {SEASONS}")
    lines = [int(x) for x in snapshot.get("lines", [])]
    tie_loss = bool(snapshot.get("tie_loss", False))
    if not lines and not tie_loss:
        raise ValueError("give at least one line index in snapshot.lines or tie_loss=true")
    state = _state(season, bool(snapshot.get("theft_aware", False)), float(snapshot.get("intensity", 3.0)))
    if any(l < 0 or l >= len(state.net.line) for l in lines):
        raise ValueError(f"line indices must be in [0, {len(state.net.line) - 1}]")
    event = Event(lines, tie_loss)
    res = mitigate(state, event)
    rec = res["recommendation"]
    out = {"season": season, "event": event.as_dict(), "stage": res["stage"],
           "before": {k: res["before"][k] for k in ("total_lost_mw", "load_lost_pct", "cascade", "ufls_mw", "verified",
                                                 "trip_sequence", "critical_lines")},
           "recommendation": {k: rec[k] for k in ("actions", "verified", "total_lost_mw", "load_lost_pct",
                                                  "max_loading_pct", "hydro_mw", "tie_mw", "n_actions")},
           "action_text": describe_actions(rec["actions"], rec, state), "hydro_bounds": state.hydro.as_dict(),
           "hidden_load_mw": state.hidden_mw, "requires_operator_approval": True, "advisory": ADVISORY}
    if with_brief:
        from cascadeguard.copilot.brief import build_facts, generate_brief
        facts = build_facts(event.as_dict(), season, res["before"], rec, res["stage"], out["action_text"],
                            state.hydro.as_dict())
        out["brief"] = generate_brief(facts)
    return out
