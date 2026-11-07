<!-- OWNER: P5 | STATUS: ACTIVE -->
# P5 — Mitigation, Case-Based Retrieval, Copilot and Dashboard

**Owner:** Person 5 (Optimization, RAG, LLM and Dashboard Lead)
**Status:** Implemented, tested and evaluated on the simulated corridor (updated 2026-11-07).
**Code:** `src/cascadeguard/{mitigation,retrieval,copilot,dashboard}/` · **Config:** `configs/mitigation/optimizer.yaml` · **Details:** `docs/p5/p5.md`

> Advisory only. The system never sends commands to equipment: the GNN predicts, the optimizer
> proposes, the simulator verifies, the language model explains, and the operator decides.

---

## 1. Mitigation model

The P1 corridor is a long radial chain fed from Sharavathi, so P5 adds one documented assumption
to give the operator a second resource: an equivalent state-grid interconnection at Nelamangala
with a 200 MW import limit. The Sharavathi slack represents the Linganamakki hydro units. Their
output is bounded by the seasonal ramp rate over a 10-minute remedial window, by seasonal
capacity, and by the daily energy budget (H2/H3). The bounds are computed with P1's own
`dispatch_hydro`.

The seasons differ sharply under this model:
- **Monsoon:** hydro carries the whole corridor (315 MW).
- **Post-monsoon:** hydro carries 354 MW, and loss of one circuit near Sharavathi overloads its
  parallel partner.
- **Summer:** with the reservoir low, hydro is held to 218 MW and about 200 MW is imported.

Available actions are tie redispatch (import up, hydro down or the reverse), controlled load
shedding at each substation, line switching, and capacitor switch-out for voltage control.

## 2. Optimizer and closed-loop verification (R9, P5-1 to P5-3)

For each contingency the post-contingency AC state is linearised by finite differences, one power
flow per control. An OR-Tools mixed-integer program (SCIP) then finds the cheapest set of actions
that keeps every line below 96 % of its rating and hydro inside its bounds. A per-action penalty
favours the smallest fix.

Every proposal is re-simulated with the P1 AC cascade engine. A plan counts as verified only if
the intended controlled shed is the only load lost, meaning no further trips, no islanded load, no
automatic under-frequency shedding, voltages within 0.92–1.08 pu and no overloads. If verification
fails, the problem is re-linearised with a tighter target. After that the greedy baseline is tried,
and finally the best unverified option is returned with an explicit flag.

Over 471 events (76 N-1, 60 N-2 and 21 tie-loss events per season), 74 lose load without action,
and **all 74 received a verified plan**:

| Season | Events losing load | No action | Greedy | Optimizer |
|---|---|---|---|---|
| Post-monsoon | 53 | 100 % lost | 0.83 % | **0.71 %** |
| Summer | 21 | 42.9 % | 29.8 % | **29.7 %** |

In post-monsoon, a single verified action, an average import increase of 41 MW, turns a full
corridor blackout into no load loss. In summer, losing the interconnection would trigger
automatic under-frequency shedding of 43 % of load. The plan instead ramps hydro by the full
80 MW its ramp and reservoir limits allow and sheds a controlled 123 MW at Peenya, for 30 % lost.
No plan violated a hydro bound.

On this radial network most events have one binding constraint, so the greedy baseline is close
to optimal. The MILP needed slightly fewer actions (1.06 against 1.11) and less shedding (2.4
against 2.9 MW). Its main value is a guaranteed minimum when several constraints interact. Events
that island all load from the only source, such as both circuits of the first section, are
reported as having no remedial action rather than receiving a fake fix.

## 3. Case-based retrieval and warm start (R8, P5-4, P5-5)

Each solved event is stored with an embedding of its post-contingency state and its verified
actions. Retrieving the three most similar past cases picked the correct action type 97 % of the
time with the physics embedding and 98 % with the GNN embedding, against 68 % for always
predicting the most common type.

Applying the precedent's actions directly, and verifying them with a single re-simulation, solved
every held-out query. That was about **5 times faster** than optimising from scratch (0.21 s against
1.10 s; 4.9 to 7.9 times across runs), with the same load loss and action count. Starting the optimizer
from the precedent instead also verified every query, in 0.59 s. The same vectors can be loaded into the P2
Qdrant `cascade_cases` collection.

## 4. Theft-aware mitigation

This experiment connects the two pillars. In monsoon, with hidden theft load of 12.5 MW (P4
estimated 12.4 MW), 22 single-circuit outages cascade on the real system. A plan built from metered
data alone judged all 22 safe, so it would have lost the whole corridor every time. Plans built on
the state that includes P4's hidden-load estimate held on the real system in **22 of 22 cases**,
with no load lost.

## 5. Incident-brief copilot (R11)

The copilot writes a short brief from facts computed by the simulator and optimizer. Guidance is
retrieved from a local corpus of seven documents: remedial-action principles, load shedding, hydro
operations, the 2003 North American and 2012 Indian disturbances, and the project's own
assumptions. Every document is marked as an illustrative summary or a project document.

When credentials are available the brief is written by Claude (`claude-opus-5-5`), with
server-side refusal fallback enabled. The output must cite only retrieved passages, use only
numbers from the facts or the sources, and avoid certainty claims; otherwise a deterministic
extractive brief is used. The brief restates the verified actions without adding any, and always
ends with the operator-approval requirement.

## 6. Operator console (P2 platform, P5-6, P5-7, P5-10)

The Streamlit and Plotly console has three tabs:
- **Grid Resilience:** corridor digital twin, contingency picker, simulator and GNN prediction,
  cascade path, critical lines, the verified plan with an apply toggle and before/after loading, similar cases, the brief, and a
  theft-aware toggle.
- **Loss & Theft:** technical vs non-technical split, feeder heatmap, suspected hidden load by
  substation, the ranked inspection list with reason codes, inspection strategy comparison and the
  false-positive audit.
- **Results:** headline numbers for both pillars.

A role selector (operator, planner, loss analyst) changes which panels appear. The API serves the
same recommender at `POST /api/mitigate`, and each response is written to the audit log with its
verification result.

## 7. Limitations

- The state-grid tie, the hydro emergency rules and the UFLS model are assumptions.
- The optimizer uses local linearisation, with simulator verification as the safeguard.
- No live LLM call has been evaluated yet; it needs an API key.
- Line switching is available to the optimizer but was never chosen: on a radial corridor, opening a
  line only adds stress.
