# OWNER: P5 | NEEDS: P1 | STATUS: ACTIVE
"""P5-3: closed-loop verification with fallback.

``mitigate`` is the end-to-end recommender:

1. simulate the event with no action (P1 cascade engine); if it is already safe, say so;
2. linearise around the post-contingency state and solve the OR-Tools MILP;
3. **verify** the proposal by re-simulating it in the P1 engine;
4. if verification fails, re-linearise at the new point with a tighter loading target
   (up to ``closed_loop_iterations``);
5. otherwise fall back to the greedy baseline, then to the best unverified option (flagged).

Every result carries ``verified``, the actions, the loss before and after, and which stage
produced it, so the dashboard and copilot can show an honest verification tick.
"""

from __future__ import annotations

import time
from typing import Any

from cascadeguard.mitigation import ADVISORY
from cascadeguard.mitigation.baselines import greedy, no_action
from cascadeguard.mitigation.network import Actions, Event, OperatingState, evaluate_outcome
from cascadeguard.mitigation.optimizer import apply_delta, sensitivities, solve_milp


def optimise(state: OperatingState, event: Event, warm: Actions | None = None,
             hint: dict[str, float] | None = None) -> dict[str, Any]:
    """MILP + closed-loop re-linearisation, starting from ``warm`` actions if given."""
    cfg = state.cfg
    opt = cfg["optimizer"]
    target = float(cfg["limits"]["loading_target_pct"])
    actions = warm or Actions()
    t0 = time.perf_counter()
    n_pf, solve_time, iterations, last = 0, 0.0, 0, None
    for it in range(int(opt["closed_loop_iterations"])):
        iterations = it + 1
        sens = sensitivities(state, event, actions, int(opt["max_switch_candidates"]), float(opt["perturb_mw"]))
        if sens is None:
            break
        n_pf += sens.n_power_flows
        res = solve_milp(sens, state, target, hint if it == 0 else None)
        solve_time += res["time_s"]
        if res["status"] == "infeasible":
            break
        actions = apply_delta(actions, res["delta"])
        last = evaluate_outcome(state, event, actions)
        if last["verified"]:
            break
        target -= float(opt["margin_step_pct"])
    if last is None:
        last = evaluate_outcome(state, event, actions)
    return {**last, "strategy": "optimizer", "iterations": iterations, "solve_time_s": solve_time,
            "time_s": time.perf_counter() - t0, "n_power_flows": n_pf}


def mitigate(state: OperatingState, event: Event, warm: Actions | None = None,
             hint: dict[str, float] | None = None, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recommend the smallest verified fix for ``event`` with fallbacks (see module docstring)."""
    t0 = time.perf_counter()
    before = baseline or no_action(state, event)
    if before["verified"]:
        return {"stage": "no_action_needed", "recommendation": before, "before": before,
                "time_s": time.perf_counter() - t0, "advisory": ADVISORY}
    candidates = []
    rec = optimise(state, event, warm, hint)
    candidates.append(("optimizer", rec))
    stage = "optimizer" if rec["verified"] else None
    if stage is None:
        g = greedy(state, event)
        candidates.append(("fallback_greedy", g))
        if g["verified"]:
            rec, stage = g, "fallback_greedy"
    if stage is None:
        # Nothing verified: return the option with the smallest total loss, clearly flagged.
        stage, rec = min(candidates + [("no_action", before)], key=lambda c: c[1]["total_lost_mw"])
        stage = f"unverified_{stage}"
    return {"stage": stage, "recommendation": rec, "before": before, "time_s": time.perf_counter() - t0,
            "advisory": ADVISORY}


def describe_actions(actions: dict[str, Any], outcome: dict[str, Any], state: OperatingState) -> list[str]:
    """Plain-language action list for operators and the copilot."""
    lines = []
    tie = float(actions.get("tie_delta_mw", 0.0))
    if abs(tie) > 0.5:
        lines.append(f"{'Raise' if tie > 0 else 'Reduce'} state-grid import at "
                     f"{state.cfg['grid_tie']['bus']} by {abs(tie):.0f} MW "
                     f"(Sharavathi hydro {'down' if tie > 0 else 'up'} accordingly).")
    hd = outcome.get("hydro_delta_mw") or 0.0
    if hd > 1.0:
        lines.append(f"Sharavathi hydro ramps up {hd:.0f} MW, within the {state.hydro.ramp_limit_mw:.0f} MW "
                     f"ramp window and the reservoir energy budget (max {state.hydro.max_mw:.0f} MW).")
    for bus, mw in sorted(actions.get("shed_mw", {}).items()):
        if mw > 0.5:
            lines.append(f"Shed {mw:.0f} MW of load at {bus}.")
    for li in actions.get("open_lines", []):
        lines.append(f"Open line {state.net.line.at[int(li), 'name']} (index {li}).")
    for cap in actions.get("caps_off", []):
        lines.append(f"Switch out capacitor bank {cap} to keep voltages inside the band.")
    if not lines:
        return ["No action required."] if outcome.get("verified") else \
            ["No verified remedial action exists in the model for this event (e.g. load is islanded "
             "from every source); prepare restoration instead."]
    if not outcome.get("verified"):
        lines.append("WARNING: this plan did not pass simulator verification.")
    return lines
