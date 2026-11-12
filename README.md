<!-- OWNER: ALL | STATUS: ACTIVE -->
# CascadeGuard-Sharavathi

AI-assisted cascade-failure prevention and non-technical loss (theft) detection on the Sharavathi–Bengaluru transmission and distribution corridor.

---

## 1. Team Roles & Responsibilities

| Role | Title | Core Scope |
|---|---|---|
| **P1** | **Grid Simulation & Search Lead** *(Critical Path)* | pandapower corridor models, AC power flow validation, cascade simulation engine, contingency enumeration (N-1, N-2, N-k), hydro operational limits. |
| **P2** | **Cloud, Data & Platform Lead** | Ray cluster compute, synthetic data generation pipeline, Parquet storage, FastAPI service architecture, schemas/contracts, CI/CD, base Docker setup. |
| **P3** | **Cascade ML Lead** | PyTorch Geometric GNN models, temporal cascade risk screening, MLflow tracking, conformal calibration, model explainability. |
| **P4** | **Theft & Loss Analytics Lead** | Technical vs non-technical loss calculation, energy balance reconciliation, consumer anomaly detection, inspection prioritization, hidden load estimation. |
| **P5** | **Optimization, RAG, Dashboard Lead** | OR-Tools line switching & hydro redispatch, pgvector/Qdrant case retrieval, Streamlit/Plotly operator console, decision explanation. |

---

## 2. Current Progress (P1–P5 delivered; P4/P5 ticks in [docs/PRD_CHECKLIST_P4_P5.md](docs/PRD_CHECKLIST_P4_P5.md))

This section records what has been implemented, validated, and integrated into the root package (`src/cascadeguard/`). All 87 automated unit and integration tests across grid physics, platform services, machine learning, theft analytics, mitigation, retrieval, copilot and dashboard are passing (26 P1–P3 + 29 P4 + 32 P5).

### P1 — Grid Simulation, AC Cascade Engine, and Search (Complete)

**Purpose:** Provide the physics-based ground truth and simulator that the ML, theft, and mitigation workstreams use.

**Delivered in root package (`src/cascadeguard/grid/`, `src/cascadeguard/sim/`):**

- **Corridor Model (`corridor_model.py`):** 39-bus, 76-line dual-circuit AC transmission network (Sharavathi to Peenya) with 34 virtual tap buses at 10 km intervals. Converged under AC Newton-Raphson power flow (`init='dc'`) with voltages within $[0.95, 1.05]$ p.u.
- **Hydro Limits & Seasonal Profiles (`hydro.py`, `seasons.py`):** Linganamakki reservoir budget (1,500 MCM dead storage, 1,035 MW turbine capacity), ramp limits, and seasonal profiles for Monsoon (900 MW max), Post-Monsoon (600 MW), and Summer (350 MW conservation with 1.15x peak demand).
- **AC Cascade Simulation Engine (`cascade_engine.py`, `islanding.py`, `trip_rules.py`):** Iterative power flow loop simulating initial contingency trips, NetworkX connected component island detection, unpowered island load shedding, and iterative overcurrent relay tripping until stabilization or corridor blackout.
- **Search & Overlays (`weak_link.py`, `attack_finder.py`, `overlays.py`, `topology_generator.py`):** Seasonal weak-link ranking, beam-search adversarial attack discovery, weather outage weights, and synthetic 30–60 bus network generator.
- **Artifacts & Tests:** `docs/p1/assumptions_sheet.csv`, `docs/p1/handoff_release1.md`, `docs/report/sec_p1.md`, and 10 passing unit tests in `tests/grid/` and `tests/sim/`.

### P2 — Cloud, Data and Platform (Local Phase Complete)

**Purpose:** Deliver reproducible datasets, shared platform interfaces, experiment tracking, Docker services, and REST API contracts.

**Delivered in root package (`src/cascadeguard/data/`, `src/cascadeguard/api/`):**

- **Cascade Scenario Generation:** Generated full-scale Parquet dataset of 8,778 scenarios (`data/processed/cascade_dataset.parquet`) across N-1 and N-2 contingencies and seasonal profiles.
- **Synthetic Smart-Meter Generation:** Generated 360,000 interval records (`data/processed/meter_readings.parquet`) across 5 theft injection types (meter bypass, meter stop, night tapping, hooking, temporary tampering) with consumer-isolated splits.
- **Throughput Benchmarking & Tracking:** Benchmark runner measuring 9,345 sequential vs. 12,762 Ray scenarios/hour logged to SQLite MLflow.
- **Container Infrastructure:** Docker Compose configuring local FastAPI, MLflow tracking, and Qdrant vector database (collections: `cascade_cases`, `theft_cases`, `documents`).
- **REST API Platform (`api/main.py`):** FastAPI service with active `/health`, `/openapi.json`, recommendation audit persistence, and now actively wired to P3 models for `/api/predict` and `/api/screen`.

### P3 — Cascade Machine Learning, Calibration, and Screening (Complete)

**Purpose:** Rapid GNN-based contingency screening, surrogate risk prediction, conformal uncertainty quantification, and graph embedding export.

**Delivered in root package (`src/cascadeguard/cascade_ml/`):**

- **Graph Builder (`graph_builder.py`):** Converts grid snapshots into PyTorch Geometric multigraphs with per-unit normalized bus features (voltage, $P, Q$, slack) and edge branch features ($R, X$, loading ratio, initial trip indicator).
- **Cascade GNN (`gnn.py`, `train.py`):** Multi-task message-passing GNN predicting line failure probabilities, cascade size, endpoint load loss in MW, and 128-dimensional scenario embeddings.
  - **Cascade ROC-AUC:** **0.9914** (vs. Random Forest baseline 0.9321).
  - **Cascade F1 Score:** **0.9886** (vs. Random Forest baseline 0.8015).
  - **Endpoint Load Loss MAE:** **14.60 MW** (vs. Random Forest baseline 22.71 MW).
- **Probability Calibration & Conformal Prediction (`calibration.py`):**
  - Temperature scaling ($T = 0.678$) reduced Expected Calibration Error (ECE) from **0.0242** down to **0.0007**.
  - Conformal prediction intervals ($q = 6.60$ MW) achieved **91.2% empirical test coverage** at a 90% confidence target.
- **High-Throughput Screening (`screening.py`):** Evaluates candidate line outages at $>800$ contingencies/second (<1 ms per contingency) for rapid operator alerts.
- **Explainability & Retrieval Export (`explain.py`, `embeddings_export.py`):** Gradient-based line attribution and exported 128-dim scenario embeddings for P5 Qdrant retrieval.
- **API Integration:** Connected to [`src/cascadeguard/api/main.py`](file:///home/gdp/Projects/EL/CASCADEGUARD/src/cascadeguard/api/main.py); `/api/predict` and `/api/screen` return live calibrated predictions.

### P4 — Theft and Loss Analytics (Complete, 2026-11-05)

**Purpose:** Separate technical loss from suspected non-technical loss (NTL), rank inspection leads with reasons, and show how hidden theft load changes cascade risk (T9).

**Delivered in root package (`src/cascadeguard/theft/`, 20 modules; config `configs/theft/models.yaml`; 26 tests in `tests/theft/`):**

- **Distribution simulator (`feeder_sim.py`):** substation → 11 kV feeder → DT → 5,281 consumers. Five injected theft types plus hard negatives (solar, new appliance, vacancy, holidays, communication gaps, unbilled loads, meter bias and drift). Exports P2 meter-contract rows.
- **T1/T2 physics (`technical_loss.py`, `energy_balance.py`):** pandapower feeder models with fitted loss curves (technical loss 2.68 % estimated vs 2.69 % true). Feeder/DT residual-change z-scores: feeder flag precision 1.00, DT flag precision 0.90.
- **T3/T4/T7 models (`features.py`, `anomaly.py`, `supervised.py`, `tamper_signals.py`, `fusion.py`, `graph_theft.py`):** fusion test AUROC **0.919**, PR-AUC **0.716**, precision@40 **0.65** (threshold baseline 0.787 / 0.388 / 0.33). ECE 0.0055 after temperature scaling; conformal coverage 88.6 %.
- **T5/T6/T10 (`reason_codes.py`, `inspection.py`, `case_retrieval.py`):** reason-coded consumer leads and DT network leads. Expected-value ranking recovers 2.2× the rule-based energy in 40 visits. Similar-past-case precedent, exportable to Qdrant `theft_cases`.
- **T9 theft-aware cascade (`hidden_load.py`):** in monsoon, SCADA-only cascade screening missed 31–81 of 196 true cascades caused by hidden theft load; the theft-aware state missed 0.
- **T8 HT tapping (`ht_tapping.py`), P4-11 fairness (`fairness.py`), P4-1 public data loader (`public_datasets.py`).**
- **API:** `POST /api/theft-score` now serves P4 leads via `theft/service.py`, with an audit record.
- **Run:** `PYTHONPATH=src python -m cascadeguard.theft.pipeline` (~4 min). **Full status, results and hand-off to-dos:** [`docs/p4/p4.md`](docs/p4/p4.md); report: [`docs/report/sec_p4.md`](docs/report/sec_p4.md).

### P5 — Mitigation, Case-Based Retrieval, Copilot and Dashboard (Complete, 2026-11-05)

**Purpose:** Recommend the smallest verified fix for a contingency (including hydro ramp within reservoir limits), reuse past cases, explain the decision, and give operators, planners and loss analysts one console.

**Delivered in root package (`src/cascadeguard/{mitigation,retrieval,copilot,dashboard}/`; config `configs/mitigation/optimizer.yaml`; extra deps `requirements-p5.txt`; 21 tests):**

- **R9 optimizer + closed loop (`mitigation/`):** AC sensitivities → OR-Tools MILP (tie/hydro redispatch, controlled shedding, switching), verified by re-simulation with the P1 cascade engine, re-linearisation, then greedy fallback. All 74 events that lose load without action got a verified plan. Post-monsoon N-1 blackouts (100 %) → 0.71 % mean loss. Summer tie loss: 42.9 % (automatic UFLS) → 29.7 % with an 80 MW hydro ramp plus controlled shed.
- **H2/H3:** hydro bounds from P1's `dispatch_hydro` (ramp window, capacity, daily energy budget, reservoir floor); 0 violations. Assumption: an equivalent state-grid tie at NELAMANGALA (200 MW).
- **R8 retrieval + warm start (`retrieval/`):** precision@3 0.97 (vs 0.68 baseline); precedent warm start about 5× faster than cold optimisation with the same pass rate.
- **Theft-aware planning (P4 link):** with 12.5 MW of hidden load in monsoon, theft-aware plans held on the true state 22/22; metered-only plans 0/22.
- **R11 copilot (`copilot/`):** cited, explanation-only incident briefs; Claude `claude-opus-5-5` with refusal fallback when credentials exist, grounded extractive brief offline; citation, number and over-claim checks.
- **Dashboard (`dashboard/`):** Streamlit + Plotly with two distinct local workspaces: a map-first Simulation Control Center and a simplified Manager Dashboard. Select configured corridor lines/feeders, run the existing cascade engine and GNN, inject a targeted synthetic feeder theft through the P4 simulator/energy-balance/scoring pipeline, compare baseline and theft-aware runs, and review incidents through the local audit store. The corridor is a configured distance schematic because the project topology does not contain geographic coordinates. `POST /api/mitigate` continues to serve verified plans with an audit record.
- **Run:** `PYTHONPATH=src python -m cascadeguard.mitigation.experiment` then `PYTHONPATH=src streamlit run src/cascadeguard/dashboard/app.py`. **Status, results, to-dos:** [`docs/p5/p5.md`](docs/p5/p5.md); demo: [`docs/p5/demo.md`](docs/p5/demo.md); report: [`docs/report/sec_p5.md`](docs/report/sec_p5.md).

---

## 3. Directory Structure with File Ownership

```text
cascadeguard-sharavathi/
├── .agent/
│   ├── role                                       # P1 (Active role tracker)
│   └── rules/ownership.md                         # P1 (Strict ownership rules)
├── .github/
│   └── workflows/ci.yml                           # P2 (CI testing pipeline)
├── configs/
│   ├── platform/
│   │   └── local.yaml                            # P2 local settings and cloud adapter seams
│   ├── cloud/
│   │   └── ray_cluster.yaml                       # P2 (Ray cluster configuration)
│   ├── grids/
│   │   ├── corridor_v0.yaml                       # P1 (Sharavathi corridor baseline topology)
│   │   ├── ieee14.yaml                            # P1 (IEEE 14 benchmark configuration)
│   │   ├── ieee39.yaml                            # P1 (IEEE 39 New England benchmark)
│   │   └── ieee118.yaml                           # P1 (IEEE 118 benchmark configuration)
│   ├── hydro/
│   │   └── hydro_limits.yaml                      # P1 (Sharavathi hydro generator & reservoir limits)
│   ├── mitigation/
│   │   └── optimizer.yaml                         # P5 [needs P1] (OR-Tools mitigation configuration)
│   ├── model/
│   │   ├── baselines.yaml                         # P3 [needs P2] (ML baseline hyperparameters)
│   │   └── gnn.yaml                               # P3 [needs P2] (GNN architecture parameters)
│   ├── seasons/
│   │   ├── monsoon.yaml                           # P1 (Monsoon dispatch & loading profiles)
│   │   ├── post_monsoon.yaml                      # P1 (Post-monsoon operating parameters)
│   │   └── summer.yaml                            # P1 (Summer peak demand profile)
│   └── theft/
│       ├── models.yaml                            # P4 [needs P2] (Theft detection model parameters)
│       └── theft_injection.yaml                   # P2 (Synthetic theft injection configuration)
├── contracts/                                     # Frozen cross-role interface schemas
│   ├── graph_tensor_format.md                     # P3 [needs P2] (GNN input tensor format specification)
│   ├── grid_snapshot.schema.json                  # P2 [needs P1] (JSON schema for grid states)
│   ├── meter_data.schema.json                     # P2 (JSON schema for consumer meter readings)
│   ├── openapi.yaml                               # P2 [needs P3, P4, P5] (FastAPI REST contract)
│   └── scenario_record.schema.json                # P2 [needs P1] (JSON schema for cascade simulation results)
├── data/                                          # (Gitignored data artifacts)
│   ├── processed/.gitkeep                         # P2 (Processed parquet feature datasets)
│   ├── raw/.gitkeep                               # P2 (Raw simulation / meter outputs)
│   └── samples/.gitkeep                           # P2 (Minimal checked-in sample data)
├── docker/
│   ├── Dockerfile.api                             # P2 (FastAPI application container)
│   ├── Dockerfile.mlflow                           # P2 (local experiment tracking service)
│   └── Dockerfile.dashboard                       # P5 [needs P2] (Streamlit dashboard container)
├── docs/
│   ├── p2/
│   │   ├── agent_context.md                       # P2 current state and continuation notes
│   │   └── local_platform_handoff.md              # P2 local commands and handoff contracts
│   ├── p1/                                        # P1 Design Artifacts & Specifications
│   │   ├── assumptions_sheet.csv                  # P1 (Tracked parameters: given/assumed/measured)
│   │   ├── handoff_release1.md                    # P1 (Release 1 handoff documentation)
│   │   ├── handoff_release2.md                    # P1 (Release 2 handoff documentation)
│   │   ├── handoff_release3.md                    # P1 (Release 3 handoff documentation)
│   │   ├── scenario_output_spec.md                # P1 (Simulation outcome data specification)
│   │   └── sources/
│   │       ├── .gitkeep                           # P1 (Directory for original source PDFs/docs)
│   │       └── sources_index.csv                  # P1 (Index of official public source documents)
│   ├── report/                                    # Final Capstone Report Sections
│   │   ├── sec_p1.md                              # P1 (Grid simulation & cascade report section)
│   │   ├── sec_p2.md                              # P2 (Platform & data architecture section)
│   │   ├── sec_p3.md                              # P3 (Cascade ML & GNN section)
│   │   ├── sec_p4.md                              # P4 (Theft & loss analytics section)
│   │   └── sec_p5.md                              # P5 (Mitigation, retrieval & dashboard section)
│   └── results_table.md                           # ALL (Shared experimental results table)
├── experiments/.gitkeep                           # P2 (MLflow tracking directory)
├── notebooks/
│   └── p1_ieee_powerflow.ipynb                    # P1 (Exploratory pandapower verification notebook)
├── scripts/
│   ├── check_ownership.py                         # P1 (Pre-commit role ownership enforcer)
│   ├── scaffold.py                                # P1 (Repository scaffolding generator)
│   └── scaffold.sh                                # P1 (Scaffold wrapper shell script)
├── src/cascadeguard/
│   ├── __init__.py                                # P1
│   ├── api/                                       # P2 [needs P3, P4, P5]
│   │   ├── __init__.py                            # P2
│   │   ├── audit.py                               # P2 (Audit logging for advisory commands)
│   │   ├── main.py                                # P2 (FastAPI application entry point)
│   │   ├── routes_resilience.py                   # P2 (Resilience & cascade screening endpoints)
│   │   ├── routes_theft.py                        # P2 (Theft analytics & scoring endpoints)
│   │   └── streaming.py                           # P2 (Server-sent events for simulation streaming)
│   ├── cascade_ml/                                # P3
│   │   ├── __init__.py                            # P3
│   │   ├── baselines.py                           # P3 [needs P2] (Random Forest & MLP baselines)
│   │   ├── calibration.py                         # P3 (Conformal prediction & score calibration)
│   │   ├── embeddings_export.py                   # P3 (Graph embeddings export for P5 case store)
│   │   ├── explain.py                             # P3 (GNNExplainer / feature attribution)
│   │   ├── gnn.py                                 # P3 [needs P2] (PyG Graph Neural Network architectures)
│   │   ├── graph_builder.py                       # P3 [needs P2] (Converts grid snapshots to PyG graphs)
│   │   ├── screening.py                           # P3 [needs P1] (High-throughput contingency screening)
│   │   └── train.py                               # P3 [needs P2] (GNN training and validation pipeline)
│   ├── common/                                    # P2
│   │   ├── __init__.py                            # P2
│   │   ├── io.py                                  # P2 (Parquet and JSON serialization helpers)
│   │   ├── logging.py                             # P2 (Structured logging configuration)
│   │   └── seed.py                                # P2 (Global deterministic seed utilities)
│   ├── copilot/                                   # P5
│   │   ├── __init__.py                            # P5
│   │   ├── brief.py                               # P5 (LLM prompt engineering for operator briefs)
│   │   └── citations.py                           # P5 (Grounding and citations generator)
│   ├── dashboard/                                 # P5
│   │   ├── __init__.py                            # P5
│   │   ├── app.py                                 # P5 [needs P2] (Streamlit main console)
│   │   └── views/
│   │       ├── __init__.py                        # P5
│   │       ├── resilience.py                      # P5 [needs P3, P4] (Corridor digital twin view)
│   │       └── theft.py                           # P5 [needs P3, P4] (Theft inspection view)
│   ├── data/                                      # P2
│   │   ├── __init__.py                            # P2
│   │   ├── meter_generator.py                     # P2 [needs P1] (Synthetic AMI smart meter generator)
│   │   ├── scenario_generator.py                  # P2 [needs P1] (Ray parallel scenario batch generator)
│   │   └── writers.py                             # P2 (Parquet dataset chunk writers)
│   ├── grid/                                      # P1 (Grid Simulation & Topologies)
│   │   ├── __init__.py                            # P1
│   │   ├── corridor_model.py                      # P1 (Sharavathi 30-60 bus corridor model)
│   │   ├── hydro.py                               # P1 (Hydro generation dispatch & reservoir constraints)
│   │   ├── loaders.py                             # P1 (IEEE benchmark loader & AC power flow gates)
│   │   ├── seasons.py                             # P1 (Seasonal load/generation scaling factors)
│   │   └── topology_generator.py                  # P1 (Synthetic corridor-like grid synthesis)
│   ├── mitigation/                                # P5
│   │   ├── __init__.py                            # P5
│   │   ├── baselines.py                           # P5 [needs P1] (Heuristic mitigation baselines)
│   │   ├── hydro_redispatch.py                    # P5 [needs P1] (Hydro dispatch adjustments via grid/hydro.py)
│   │   ├── optimizer.py                           # P5 [needs P1] (OR-Tools MIP/CP-SAT line switching)
│   │   └── verifier.py                            # P5 [needs P1] (Simulator re-run to verify mitigation)
│   ├── retrieval/                                 # P5
│   │   ├── __init__.py                            # P5
│   │   ├── case_store.py                          # P5 [needs P2, P3] (Vector database interface for past cascades)
│   │   └── warm_start.py                          # P5 (Extracts warm-start actions from retrieved cases)
│   ├── sim/                                       # P1 (Cascade Engine & Contingency Simulation)
│   │   ├── __init__.py                            # P1
│   │   ├── attack_finder.py                       # P1 [needs P3] (Adversarial N-k search)
│   │   ├── cascade_engine.py                      # P1 (Iterative AC cascade failure engine)
│   │   ├── contingency.py                         # P1 (Exhaustive N-1, N-2, N-k enumeration)
│   │   ├── islanding.py                           # P1 (Network split detection & island rebalancing)
│   │   ├── outcomes.py                            # P1 (Typed scenario outcome records)
│   │   ├── overlays.py                            # P1 (Weather & renewable stress overlays)
│   │   ├── trip_rules.py                          # P1 (Overcurrent relay models & trip thresholds)
│   │   └── weak_link.py                           # P1 [needs P3] (Weak-link ranking)
│   └── theft/                                     # P4
│       ├── __init__.py                            # P4
│       ├── anomaly.py                             # P4 [needs P2] (Unsupervised consumption anomaly models)
│       ├── energy_balance.py                      # P4 [needs P2] (Substation energy balance reconciliation)
│       ├── fairness.py                            # P4 (Demographic parity / bias audit)
│       ├── fusion.py                              # P4 (Multi-model theft score fusion)
│       ├── graph_theft.py                         # P4 (Neighborhood graph anomaly detection)
│       ├── hidden_load.py                         # P4 [needs P1, P3] (Theft-aware grid state & unmetered load)
│       ├── ht_tapping.py                          # P4 [needs P1] (Direct HT feeder tapping screening)
│       ├── inspection.py                          # P4 (Prioritized inspection target ranking)
│       ├── reason_codes.py                        # P4 (Human-readable explanations for field crews)
│       ├── supervised.py                          # P4 [needs P2] (Supervised theft classification)
│       ├── tamper_signals.py                      # P4 (Smart meter tamper flag analysis)
│       └── technical_loss.py                      # P4 [needs P1] (Power-flow derived physical line losses)
├── tests/
│   ├── __init__.py                                # P1
│   ├── api/__init__.py                            # P2 [LOCKED]
│   ├── cascade_ml/__init__.py                     # P3 [LOCKED]
│   ├── dashboard/__init__.py                      # P5 [LOCKED]
│   ├── data/__init__.py                           # P2 [LOCKED]
│   ├── grid/                                      # P1
│   │   ├── __init__.py                            # P1
│   │   └── test_loaders.py                        # P1 (AC power flow convergence tests)
│   ├── mitigation/__init__.py                     # P5 [LOCKED]
│   ├── retrieval/__init__.py                      # P5 [LOCKED]
│   ├── sim/__init__.py                            # P1
│   └── theft/__init__.py                          # P4 [LOCKED]
├── .env.example                                   # P2 (Environment variables template)
├── .gitignore                                     # P2 (Git exclusion rules)
├── CODEOWNERS                                     # P2 (GitHub code review owners mapping)
├── docker-compose.yml                             # P2 (local API, MLflow and Qdrant services)
├── Makefile                                       # P2 (Build and automation commands)
├── OWNERSHIP.md                                   # P1 (Project role mapping & boundaries)
├── README.md                                      # ALL (Project overview and architecture)
├── requirements-api.txt                           # P2 (small API container dependencies)
├── pyproject.toml                                 # P2 (Python packaging configuration)
└── requirements.txt                               # P2 (Core dependencies)
```

## Imported working demo application

The main application and its cascade simulator, theft analytics, FastAPI service, Streamlit dashboard, retrieval resources, tests, and data artifacts are maintained in the root package and `src/cascadeguard/`.

The ten original design notes are preserved under `docs/specifications/`. The root `src/cascadeguard/` package is the single maintained application implementation.

Install the main application with `make install` from the repository root. Local API, dashboard, data-generation, and test commands are provided by the root Makefile.

### Windows click-to-run launcher

`CascadeGuard.exe` in the project root starts the existing Streamlit dashboard on `127.0.0.1:8501` and opens it in your browser. Keep the executable beside the project folders; it uses the local models and data already in this repository. The first launch creates `.venv` and installs missing project packages if needed. The launcher window also has Open and Stop controls. To rebuild the executable from source, run `powershell -ExecutionPolicy Bypass -File tools/windows/build_exe.ps1`.
