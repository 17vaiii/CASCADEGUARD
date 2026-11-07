<!-- OWNER: ALL | STATUS: ACTIVE -->
# CascadeGuard-Sharavathi Experimental Results Table

## Cascade ML (P3) Benchmarks on Sharavathi Corridor

| Model | Cascade Detection ROC-AUC | Cascade F1 Score | Endpoint Load Loss MAE (MW) | Calibrated ECE | Conformal Coverage (90% Target) |
|---|---|---|---|---|---|
| **Logistic Regression** | 0.9321 | 0.8015 | 23.17 MW | 0.0412 | N/A |
| **Random Forest Baseline** | 0.9321 | 0.8015 | 22.71 MW | 0.0385 | N/A |
| **Cascade GNN (PyG)** | **0.9914** | **0.9886** | **14.60 MW** | **0.0007** | **91.2%** |

*Snapshot Date: 2026-11-01. Dataset: 8,778 scenarios (70/15/15 train/val/test split).*

## Theft & Loss Analytics (P4) on the simulated Sharavathi distribution layer

**Consumer-level detection** (held-out test split: 792 consumers, 40 injected thefts; K = 40 inspections; random precision 0.05)

| Model | AUROC | PR-AUC | Precision@K | ECE |
|---|---|---|---|---|
| Threshold baseline (consumption drop) | 0.787 | 0.388 | 0.325 | N/A |
| Isolation Forest | 0.718 | 0.293 | 0.225 | N/A |
| Autoencoder | 0.740 | 0.405 | 0.425 | N/A |
| Peer-group deviation | 0.781 | 0.371 | 0.375 | N/A |
| Gradient boosting | 0.917 | 0.711 | 0.650 | 0.0214 |
| GraphSAGE (feeder–DT–consumer graph) | 0.902 | 0.674 | 0.625 | N/A |
| **Fusion (calibrated, shipped)** | **0.919** | **0.716** | **0.650** | **0.0055** |

Fusion conformal coverage at a 90 % target: 88.6 %. Recall@K by type: bypass, stop and tampering 1.00; hooking and night tapping 0.12 (meters unchanged, so these are found through DT network leads).

**Energy balance (T1/T2):** technical-loss estimate 2.68 % vs true 2.69 % of feeder input. Feeder flags at z ≥ 3: precision 1.00, recall 0.62. DT flags: precision 0.90, recall 0.83.

**Inspection (T6, 40 visits):** recovered 105,869 kWh with expected-value + route ranking, vs 48,997 kWh rule-based and 700 kWh random.

**Theft-aware cascade (T9, monsoon, 196 contingencies):** SCADA-only simulation missed 31 / 81 / 81 true cascades at 1× / 3× / 5× simulated NTL; the theft-aware state missed 0, and load-loss MAE fell from 49–135 MW to < 0.1 MW.

**Cascade GNN retrained on the root corridor with hidden load (separate checkpoint):** AUROC 0.9996, F1 0.986, load-loss MAE 6.0 MW (Random Forest 0.82, 0.69, 108 MW), ECE 0.012, conformal coverage 90.1 %. T9, monsoon 3x NTL: GNN load-loss MAE 130 MW on the metered state, 2.8 MW on the theft-aware state.

**HT tapping (T8):** 0 % false alarms; recall 83 % for 15–30 MW taps; median location error 20 km.

*Snapshot date: 2026-11-07. Seed 42; 5,281 simulated consumers. Details: `docs/p4/p4.md`, `data/models/theft/theft_metrics.json`.*

## Mitigation, Retrieval and Copilot (P5) on the Sharavathi corridor

**Mitigation** (471 events: per season 76 N-1, 60 sampled N-2, 21 tie-loss events; 74 lose load without action; every plan re-simulated with the P1 AC cascade engine)

| Season | Events losing load | No action (mean load lost) | Greedy | Optimizer (OR-Tools MILP) | Verified plans (optimizer / greedy) |
|---|---|---|---|---|---|
| Post-monsoon | 53 | 100 % | 0.83 % | **0.71 %** | 100 % / 100 % |
| Summer | 21 | 42.9 % | 29.76 % | **29.75 %** | 100 % / 100 % |

Optimizer: 1.06 mean actions (greedy 1.11); 0 hydro-bound violations; 17–27 ms per MILP solve.

**Case-based retrieval:** precision@3 of action type 0.97 physics, 0.98 GNN embedding, vs 0.68 majority baseline. **Warm start:** 5.3× faster than cold optimisation (0.21 s vs 1.10 s; 4.9-7.9× across runs) with the same pass rate (100 %) and load loss.

**Theft-aware planning (monsoon, 12.5 MW hidden load):** plans built on P4's theft-aware state held on the true state in 22 of 22 cascading events (0 % loss); metered-only plans held in 0 of 22 (100 % loss).

*Snapshot date: 2026-11-07. Seed 42. Details: `docs/p5/p5.md`, `data/models/mitigation/mitigation_metrics.json`.*
