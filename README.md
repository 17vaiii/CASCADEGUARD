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

## 2. Current P1 and P2 Progress

This section records what has been delivered, why it exists, and the remaining handoffs. “Completed” means implemented in the local project; it does not mean deployed to AWS or validated against private utility data.

### P1 — Grid Simulation and Search

**Purpose:** provide the physics-based ground truth and simulator that the ML, theft, and mitigation workstreams use. It models how outages, hydro dispatch, and changing operating seasons affect power flow and cascade risk on a clearly labelled, assumed Sharavathi–Bengaluru corridor.

**Delivered:**

- IEEE 14/39/118 power-flow benchmarks and the reduced corridor model, with topology assumptions documented.
- AC power-flow cascade simulation with outage trips, re-solves, island handling, load shedding, and labelled outcomes.
- Seasonal operating profiles and hydro dispatch constrained by ramp, energy, inflow, and minimum-reservoir assumptions.
- Synthetic corridor-like topologies, seasonal weak-link reports, and simulator-only contingency/attack search.
- Scenario and handoff artifacts used to generate local cascade data for downstream work.

**Remaining integration/limitations:** weather weights and renewable variations are not yet carried through the scenario dataset and screening pipeline; GNN-guided attack search needs P2/P3 model integration. The corridor and hydro parameters remain assumptions, not a verified KPTCL model. See [P1 implementation notes](theft_detection/docs/PERSON1_GRID_SIMULATION.md) and [corridor assumptions](theft_detection/docs/CORRIDOR_ASSUMPTIONS.md).

### P2 — Cloud, Data and Platform

**Purpose:** make reproducible, labelled data and shared platform interfaces available to the other workstreams, then provide scalable generation, experiment tracking, and a deployable API. P3 needs cascade scenario data; P4 needs synthetic meter data; P5 ultimately needs the service/API handoff.

**P2 status after local-phase implementation (code/configuration complete; runtime validation pending):**

- Cascade scenario generation now has sequential, joblib, and Ray backends. Parquet output defaults to local disk and supports fsspec S3/GCS URIs when their drivers and credentials are configured.
- A repeatable throughput benchmark records sequential and Ray scenarios/hour, workload settings, elapsed time, and whether Ray ran locally or on an attached cluster. The cloud cluster comparison still needs the future cluster.
- The consumer interval-meter generator emits ground-truth labels for meter bypass, meter stop, night tapping, hooking, and temporary tampering, with consumer-level train/validation/test splits. Its Parquet output has not yet been generated in this environment.
- Local MLflow and Qdrant services are configured in Compose. The Qdrant initializer creates `cascade_cases`, `theft_cases`, and `documents`; the MLflow helper gives each workstream a shared tracking interface.
- A local FastAPI Docker service exposes the PRD route contracts. Predict, screen, mitigation, and theft-score routes intentionally return dependency-not-ready responses until P3/P4/P5 register those implementations. Health and audit routes are implemented.
- Recommendation audit records and verification outcomes persist in SQLite locally with references and a data fingerprint.

**Verification boundary:** syntax compilation, YAML/JSON parsing, static API-to-OpenAPI route matching, SQLite audit create/verify/read, and `git diff --check` passed. HTTP service startup, Docker builds, Qdrant/MLflow startup, Ray generation, meter Parquet generation, and throughput measurements have not run: the available Python environment lacked the runtime dependencies and Docker was unavailable. Do not describe the API or generated datasets as runtime-verified until those steps pass.

**Deferred:** cloud accounts, S3/GCS provisioning, a Ray cluster, Cloud Run/ECS deployment, and cloud cost/throughput measurements remain future-phase tasks. P2-10 Kafka/Pub/Sub telemetry remains a stretch item. The [P2 agent context](docs/p2/agent_context.md) is the recommended starting point for the next coding agent; the [P2 local handoff](docs/p2/local_platform_handoff.md) contains commands, schemas, and samples. Use synthetic or public data only.

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

The previously developed full-stack demonstration is now stored in `theft_detection/` to match this repository's existing module layout. It includes the corridor simulator, theft ML models and checkpoints, FastAPI backend, React frontend, RAG resources, tests, documentation, and generated datasets. Its local run instructions are in [theft_detection/README.md](theft_detection/README.md).

The ten original design notes are preserved under `docs/specifications/`. The root `src/cascadeguard/` package remains the role-based project implementation area; the imported demo is a self-contained application module and has not yet been refactored into that package.

Dependency folders and machine-specific files (`.venv`, `node_modules`, caches, `.env`, and runtime logs) are intentionally not copied. For the imported demo, install dependencies from `theft_detection/requirements.txt` and `theft_detection/frontend/package-lock.json`. For the PRD P2 platform work, use `make p2-install` from the repository root.
