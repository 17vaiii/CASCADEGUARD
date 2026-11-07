# OWNER: P5 | STATUS: ACTIVE
"""P5-5: warm-start the optimizer from retrieved precedent cases.

For a new event the most similar past cases are retrieved. Their verified actions are adapted
to the current bounds and tried directly in the P1 simulator (one re-simulation each). If one
verifies, the operator gets a verified recommendation without building sensitivities or solving
the MILP. Otherwise the best precedent seeds the closed-loop optimizer: re-linearisation
starts from its actions instead of from no action. Gains are measured against the cold-start optimizer.
"""

from __future__ import annotations

import time
from typing import Any

from cascadeguard.mitigation import ADVISORY
from cascadeguard.mitigation.network import Actions, Event, OperatingState, evaluate_outcome
from cascadeguard.mitigation.verifier import optimise
from cascadeguard.retrieval.case_library import CascadeCaseLibrary


def _adapt(actions: dict[str, Any], state: OperatingState, event: Event) -> Actions:
    a = Actions.from_dict(actions)
    if event.tie_loss:
        a.tie_delta_mw = 0.0
    tie = state.cfg["grid_tie"]
    a.tie_delta_mw = max(min(a.tie_delta_mw, tie["max_import_mw"] - state.tie_mw), tie["min_import_mw"] - state.tie_mw)
    a.open_lines = [l for l in a.open_lines if l not in event.lines]
    return a


def warm_mitigate(state: OperatingState, event: Event, library: CascadeCaseLibrary, k: int = 3,
                  before: dict[str, Any] | None = None, try_direct: bool = True) -> dict[str, Any]:
    t0 = time.perf_counter()
    vec = library.embed(state, event)
    matches = library.query(vec, k) if vec is not None else []
    sims = 0
    before = before or evaluate_outcome(state, event, Actions())
    if before["verified"]:
        return {"stage": "no_action_needed", "recommendation": before, "before": before, "matches": matches,
                "time_s": time.perf_counter() - t0, "simulations": 0, "advisory": ADVISORY}
    for m in (matches if try_direct else []):
        if not m["verified"] or m["signature"] in ("none", "unmitigable"):
            continue
        cand = _adapt(m["actions"], state, event)
        out = evaluate_outcome(state, event, cand)
        sims += 1
        if out["verified"]:
            return {"stage": "precedent_direct", "recommendation": {**out, "strategy": "precedent"},
                    "before": before, "matches": matches, "precedent": m["case_id"],
                    "time_s": time.perf_counter() - t0, "simulations": sims, "n_power_flows": 0,
                    "advisory": ADVISORY}
    best = next((m for m in matches if m["verified"]), None)
    warm = _adapt(best["actions"], state, event) if best else None
    rec = optimise(state, event, warm=warm)        # re-linearise starting from the precedent's actions
    stage = "precedent_warm_optimizer" if rec["verified"] else "precedent_unverified"
    return {"stage": stage, "recommendation": rec, "before": before, "matches": matches,
            "precedent": best["case_id"] if best else None, "time_s": time.perf_counter() - t0,
            "simulations": sims + rec.get("iterations", 0), "n_power_flows": rec.get("n_power_flows", 0),
            "advisory": ADVISORY}
