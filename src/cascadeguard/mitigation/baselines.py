# OWNER: P5 | NEEDS: P1 | STATUS: ACTIVE
"""P5-1: no-action and greedy mitigation baselines.

* **No action** - the event runs through the P1 cascade engine untouched.
* **Greedy** - repeatedly fix the single worst violation (most loaded line above target, or a
  hydro deficit) with the one control that removes it at the lowest cost per unit of relief,
  sized from the local AC sensitivity, until no violation remains. This is how a rule-based
  remedial action scheme works; it has no global view of several overloads at once.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from cascadeguard.mitigation.network import Actions, Event, OperatingState, evaluate_outcome
from cascadeguard.mitigation.optimizer import apply_delta, sensitivities


def no_action(state: OperatingState, event: Event) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = evaluate_outcome(state, event, Actions())
    return {**out, "strategy": "no_action", "time_s": time.perf_counter() - t0, "n_power_flows": 0}


def _unit_cost(kind: str, costs: dict[str, float]) -> float:
    return {"tie": costs["tie_per_mw"], "shed": costs["shed_per_mw"], "switch": costs["switch"]}[kind]


def greedy(state: OperatingState, event: Event) -> dict[str, Any]:
    cfg = state.cfg
    target = float(cfg["limits"]["loading_target_pct"])
    costs = cfg["costs"]
    actions = Actions()
    n_pf = 0
    t0 = time.perf_counter()
    for _ in range(int(cfg["greedy"]["max_steps"])):
        sens = sensitivities(state, event, actions, max_switch=0, step=float(cfg["optimizer"]["perturb_mw"]))
        if sens is None:
            break
        n_pf += sens.n_power_flows
        worst = int(np.argmax(sens.loading0)) if len(sens.lines) else -1
        over = sens.loading0[worst] - target if worst >= 0 else -1.0
        deficit = sens.hydro0 - state.hydro.max_mw
        if over <= 0 and deficit <= 0.5:
            break
        best = None
        for k, (name, kind) in enumerate(zip(sens.controls, sens.kinds)):
            if over > 0:
                rate = sens.S[worst, k]              # loading change per unit
                need = over / -rate if rate < -1e-6 else None
            else:
                rate = sens.H[k]
                need = deficit / -rate if rate < -1e-6 else None
            if need is None:
                continue
            # The control may be used in its feasible direction only.
            amount = min(need * 1.02, sens.upper[k]) if need > 0 else max(need, sens.lower[k])
            if abs(amount) < 1e-6:
                continue
            relief = abs(amount * rate)
            score = relief / (abs(amount) * _unit_cost(kind, costs) + costs["per_action"])
            if best is None or score > best[0]:
                best = (score, name, amount)
        if best is None:
            break
        actions = apply_delta(actions, {best[1]: best[2]})
    out = evaluate_outcome(state, event, actions)
    return {**out, "strategy": "greedy", "time_s": time.perf_counter() - t0, "n_power_flows": n_pf}
