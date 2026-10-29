# CascadeGuard-Sharavathi — Grid Resilience & Theft Intelligence

Studies cascading outages, seasonal hydro dispatch, and **suspected unauthorized
power extraction** on a simulated 361 km, 220 kV corridor from Sharavathi to
Peenya, Bengaluru. The existing theft detection pipeline and interactive
FastAPI + React control room are implemented. Cascade simulation and hydro
handoff artifacts are also present; the cascade GNN and mitigation work remain
in progress (see [current progress](#current-project-progress)).

> **Simulation only.** The corridor is a *proposed simplified model*, not a verified KPTCL replica, and every
> result is a *suspected* anomaly that needs field verification. The system never controls a real grid.

![Scenario Lab — a 25 MW extraction at km 150 is detected and localized to km 163 (80 % interval 140–180 km)](docs/screenshots/scenario-lab.png)

---

## Contents
- [Team ownership and handoffs](docs/TEAM_OWNERSHIP.md)
- [Cross-person contracts](contracts/README.md)
- [What it does](#what-it-does)
- [Results](#results)
- [Current project progress](#current-project-progress)
- [Quick start (Docker)](#quick-start-docker)
- [Run without Docker](#run-without-docker)
- [Using the app](#using-the-app)
- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Retraining from scratch](#retraining-from-scratch)
- [Tests](#tests)
- [Assumptions & limitations](#assumptions--limitations)

---

## What it does

| | |
|---|---|
| **Detect** | Is the corridor behaving normally, or is there an unexplained anomaly? |
| **Classify** | Is the anomaly likely an *extraction*, a *sensor fault* (bias / drift / missing data) or another network event? |
| **Localize** | Where along the 361 km line? It gives an estimated km, an 80 % interval and the most likely 10 km tap points. |
| **Advise** | Rule-based inspection steps plus a RAG advisor that answers with cited guidance passages. |
| **Study sensors** | How much do extra meters (Sira junction, every tap) improve detection and localization? |
| **Study grid resilience** | Run seasonal N-1/N-2 cascade scenarios and review weak-link and attack reports. These are offline research tools, not yet an interactive resilience tab. |

The corridor has 5 substations. Only 4 are metered by default, so the Sira junction is *unmetered*. Each line is
split into **virtual tap buses every 10 km**; these are the candidate extraction points. A theft is simulated as a
real extra load at a tap, followed by a full AC power-flow re-run. Meter readings are never just edited.

## Results

All numbers come from held-out data: scenario groups never seen in training, plus a **leave-location-out** split
(taps at 40/50/130/140/250/260 km are never seen during training).

**Detection (test split, 1,919 scenarios)**

| Model | Precision | Recall | F1 | False-positive rate | ROC-AUC | Recall @ 1 % FPR |
|---|---|---|---|---|---|---|
| **XGBoost** | 98.6 % | **91.5 %** | **94.9 %** | 2.8 % | **0.976** | **89.8 %** |
| GNN (GraphSAGE) | 99.1 % | 90.1 % | 94.4 % | 1.8 % | 0.972 | 89.8 % |
| Residual baseline | 99.3 % | 56.0 % | 71.6 % | 0.8 % | 0.792 | 56.0 % |

**Localization (unseen locations, 1,155 scenarios)**

| Method | Mean error | Median error | Within 10 km | Within 25 km | Within 50 km |
|---|---|---|---|---|---|
| **GNN (GraphSAGE)** — used by the app | **21.3 km** | **14.3 km** | 37 % | 73 % | 91 % |
| XGBoost regression | 23.1 km | 15.3 km | 37 % | 70 % | 88 % |
| Physics baseline | 49.9 km | 42.0 km | 14 % | 33 % | 57 % |

The GNN numbers are the mean of 3 training seeds (test-split mean error 19.1 ± 0.8 km).
Bigger thefts are easier to place: the median error is about 10 km for 15–40 MW, 19 km for 5–15 MW and
36 km for 1–5 MW. Metering every tap (the *dense* profile) cuts the mean error from 21.3 km to 15.5 km.
See the Sensor Study page.

<table>
<tr>
<td><img src="docs/screenshots/metrics.png" alt="Metrics page"></td>
<td><img src="docs/screenshots/sensor-study.png" alt="Sensor study page"></td>
</tr>
<tr>
<td align="center"><b>Metrics</b> — AI vs baseline on held-out data</td>
<td align="center"><b>Sensor Study</b> — 3 metering profiles × 4 noise levels</td>
</tr>
</table>

---

## Current project progress

**Status reviewed:** 29 October 2026. This snapshot reflects repository files,
generated artifacts, and the simulator checks recorded for this project. The
PDF's role assignments are used for Person 1; Persons 2, 3, and 4 follow the
team roles supplied in the project brief. See the [ownership map](docs/TEAM_OWNERSHIP.md)
and [handoff contracts](contracts/README.md) before editing.

| Workstream | Status | Current state |
|---|---|---|
| **Person 1 - Grid simulation and search (PDF P1)** | **Core implemented; integration gaps remain** | Simulator, benchmarks, hydro, synthetic topology generator, and weak-link reporting are in place. Weather/renewable overlays are not yet included in the scenario dataset or used to weight contingency screening, and GNN-fitness search awaits P2 model integration. |
| **Person 2 - Cascade ML and explainability** | **Handoff ready; implementation not started** | `cascade_ml/` has R3-R7 entry points. The 8,778-row N-1/N-2 artifact now includes ordered pre-contingency graph features. Legacy `line_*_loading` and `bus_*_vm_pu` fields are post-cascade outputs and must not be used as inputs. N-3 scenarios are not in this artifact. |
| **Person 3 - Optimization, RAG and full-stack** | **Partial** | Existing FastAPI, React, and RAG features are present and the dashboard/API start locally. Mitigation remains a stub; OR-Tools optimization and closed-loop cascade verification are outstanding. |
| **Person 4 - Theft and loss intelligence** | **Partial** | Existing corridor extraction detection and tap localization are present. The new `loss_intelligence/` area is only a scaffold; feeder energy balance, interval-meter anomaly fusion, inspection ranking, and the T9 theft-aware cascade experiment remain to be completed. |

### Person 1 audit against the product PRD

This uses the PDF's Person 1 assignment: R1, R10, H1, H3, H4, H5, and H6,
plus work items P1-1 through P1-9. It keeps P2's scenario-export and GNN
implementation paths separate from P1's ground-truth simulator.

| PRD requirement | Status | Evidence and boundary |
|---|---|---|
| **R1 / P1-2 - Cascade engine** | **Implemented and tested** | `grid/cascade.py` performs AC re-solves, overload trips, island detection and load shedding; dedicated P1 acceptance tests cover its trace and trip output. |
| **P1-1 - IEEE 14/39/118 benchmarks** | **Implemented and verified** | `grid/benchmarks.py` runs the built-in pandapower cases; all three converged and exported to `data/processed/ieee_benchmarks.csv`. |
| **P1-3 - Reduced corridor model** | **Implemented with explicit assumptions** | The 39-bus model and assumptions are documented in `docs/CORRIDOR_ASSUMPTIONS.md`. Public KPTCL material does not provide enough complete one-line/parameter data to claim a verified replica. |
| **H1 / P1-4 - Seasonal cases** | **Implemented** | Monsoon, post-monsoon, and summer profiles configure seasonal load and bounded hydro dispatch. |
| **H3 / P1-5 - Reservoir constraints** | **Implemented** | `dispatch_hydro` and `simulate_hydro_day` carry ramp, energy, inflow, water, and minimum-storage state through a day. All operating parameters remain assumed until confirmed by an operator. |
| **P1-6 - Generalization topologies** | **Implemented** | `grid/topology_variants.py` deterministically generates corridor-like synthetic 30–60 bus networks. |
| **H4 / P1-7 - Seasonal weak links** | **Implemented** | `grid/attack_finder.py` produces a per-season Bengaluru load-loss ranking; the existing Parquet report contains 60 rows. |
| **R10 / P1-8 - Worst-case attack finder** | **Partial; GNN integration pending** | Greedy/beam and minimum-k simulator searches are available. `gnn_guided_search` accepts P2's scorer and verifies finalists with AC simulation, but it cannot run end-to-end until P2 supplies the trained scorer. |
| **H5 - Weather overlay (stretch)** | **Partial** | `grid/weather.py` calculates synthetic scenario-dependent outage weights, but the scenario generator and N-k screening do not yet consume those weights. |
| **H6 - Renewable variability** | **Partial** | `grid/renewables.py` generates and applies seasonal solar/wind profiles, but the cascade dataset does not yet include renewable variations as scenario features. |

**P1 conclusion:** core simulation, hydro, topology variants, weak-link reporting,
and simulator-only attack search are implemented and tested. P1 is not fully
complete against the PRD: weather weights still need to feed screening, renewable
scenarios still need to enter the dataset, and GNN-fitness search needs P2's model.
Operator-grade corridor and hydro values also remain unverified assumptions. P2's
scenario artifact is available now, so these integration tasks do not block P2's
graph/model work.

**Verification:** `pytest tests/test_person1_prd.py tests/test_grid.py -q` passed
(33 tests, 44.56 seconds). IEEE 14/39/118 AC power flow converged. Pandapower
emitted six upstream deprecation warnings during the benchmark test.
The existing 8,778-row N-1/N-2 artifact includes the new `cascade_graph_v1`
pre-event features. Its legacy wide voltage/loading columns remain available as
outcome diagnostics and are identified as leakage-prone inputs in the handoff
contract. N-3 rows are not included.

### Current generated cascade outputs

- `data/processed/cascade_dataset.parquet` - 8,778 N-1/N-2
  scenarios, 2,926 per season.
- `data/processed/weak_link_report.parquet` - 60 rows, 20 per
  season.
- `data/processed/attack_report.parquet` - 120 ranked rows
  across season and contingency size.

These are local generated artifacts and may be ignored/untracked by Git. Follow
the contracts when regenerating or passing them to another workstream.

---

## Quick start (Docker)

The easiest way to run it: trained models and the dataset are included, so nothing needs training.

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/). On Windows, install
WSL 2 first by running `wsl --install` in an admin PowerShell and restarting.

```bash
# Run from the CASCADEGUARD repository root:
cd theft_detection
cp .env.example .env          # Windows PowerShell: copy .env.example .env
docker compose up --build
```

The first build takes about 5–10 minutes (it downloads PyTorch). Then open:

| | URL |
|---|---|
| **Web app** | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |

Stop it with `Ctrl+C`, or `docker compose down`.

## Run without Docker

**Requirements:** Python 3.12, Node.js 20.

```bash
cd theft_detection

# 1. Python dependencies (CPU-only PyTorch, then the pinned list)
pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 2. Frontend dependencies
cd frontend && npm install && cd ..

# 3. Start the API (terminal 1)
cd backend && python -m uvicorn app.main:app --port 8000

# 4. Start the website (terminal 2)
cd frontend && npm run dev
```

Open http://localhost:5173. If you have `make`, the repo-root `Makefile` wraps all of this:
`make install`, `make dev`, `make test`, `make help`.

---

## Using the app

| Page | What you can do |
|---|---|
| **Overview** | Corridor diagram (metered ◉ vs unmetered substations), headline metrics, the "honest claim", assumptions. |
| **Scenario Lab** | Inject an extraction (location, MW), change load, noise, sensor profile or a sensor fault, then **Run**. See detection, likely cause, estimated location, recommended actions and the RAG advisor. **Reveal truth** shows the real location and the error. |
| **Replay** | Streams held-out test scenarios over a WebSocket, one per tick, with live detection and a scrubbable alert timeline. |
| **Metrics** | Precision/recall/ROC, confusion matrix, per-class recall, localization error vs baselines. |
| **Sensor Study** | Detection and localization for 3 metering profiles × 4 noise levels, plus which tap pairs are physically indistinguishable. |
| **Console** | Live activity log: user actions, simulations, alerts and API calls. Press <kbd>`</kbd> to open the dock from any page. |
| **Mitigation** | Placeholder for future load-balancing work (locked, "coming soon"). |

**Keyboard shortcuts (Scenario Lab):** <kbd>R</kbd> run · <kbd>T</kbd> reveal truth · <kbd>←</kbd>/<kbd>→</kbd> move the
injection ±10 km · **Live mode** re-runs on every change.

**Suggested 2-minute demo:** Scenario Lab → *Preset: Big theft near Shimoga* → **Run** → **Reveal truth** →
*Ask the advisor* → *Preset: Sensor bias only* → Run (the likely cause flips to *sensor error*). A longer script
is in [docs/DEMO.md](docs/DEMO.md).

<table>
<tr>
<td><img src="docs/screenshots/overview.png" alt="Overview page"></td>
<td><img src="docs/screenshots/replay.png" alt="Live replay page"></td>
</tr>
<tr>
<td align="center"><b>Overview</b> — corridor and headline metrics</td>
<td align="center"><b>Replay</b> — live stream of held-out scenarios</td>
</tr>
<tr>
<td colspan="2"><img src="docs/screenshots/console.png" alt="Activity console"></td>
</tr>
<tr>
<td colspan="2" align="center"><b>Console</b> — every action, simulation and alert, live</td>
</tr>
</table>

---

## How it works

```mermaid
flowchart LR
    A[config/*.yaml<br/>topology, sensors,<br/>scenarios] --> B[grid/<br/>pandapower<br/>AC power flow]
    B --> C[simdata/<br/>synthetic scenarios<br/>+ noisy metering]
    C --> D[ml/features<br/>41 physics features<br/>residuals, KCL, losses]
    D --> E[XGBoost<br/>detect + classify]
    D --> F[GNN GraphSAGE<br/>localize km + interval]
    E --> G[FastAPI backend<br/>REST + WebSocket]
    F --> G
    H[rag/ advisor<br/>+ vectordb/ similar cases] --> G
    G --> I[React control room]
```

1. **Grid model** (`grid/`): pandapower model of the 5-substation chain with 10 km tap buses, line parameters
   and loads from `config/topology.yaml`. Every assumed value is tagged `source: assumed`.
2. **Synthetic data** (`simdata/`): thousands of scenarios (normal operation at varied load, thefts of 1–40 MW at
   every tap, sensor bias/drift/missing data, network events). Each runs a full AC power flow, then adds
   realistic meter noise. Data is split by scenario group, and some locations are held out entirely, to prevent leakage.
3. **Features** (`ml/features.py`): 41 physics-informed features, such as residuals against the expected
   power flow, Kirchhoff current-law consistency between metered ends, and loss mismatches.
4. **Models** (`ml/`): a residual-threshold **baseline**, **XGBoost** for detection and 6-class cause
   classification (with SHAP explanations), and XGBoost regression/tap-ranking plus a **GraphSAGE GNN** for
   localization with calibrated 80 % intervals. The GNN is used because it beats XGBoost on unseen locations.
5. **Backend** (`backend/`): FastAPI endpoints for simulate → analyze, metrics, sensor study, scenario replay
   (WebSocket), activity events (WebSocket), the RAG advisor and similar-case search.
6. **Frontend** (`frontend/`): React + TypeScript + Vite, Plotly charts, React Flow corridor diagram,
   TanStack Query, Zustand and Tailwind. Built for keyboard access, with Lighthouse accessibility 96–100 on every page.

**Tech stack:** Python 3.12 · pandapower · scikit-learn · XGBoost · SHAP · PyTorch + PyTorch Geometric ·
FastAPI · React 18 · TypeScript · Vite · Plotly · React Flow · Tailwind · Vitest · Playwright · Docker

<details>
<summary>Grid diagnostics (voltage profile and theft effect)</summary>

![Voltage profile along the corridor](figures/voltage_profile.png)
![Normal vs theft comparison](figures/theft_comparison.png)
</details>

## Project structure

```
.
├─ README.md
├─ Makefile                  # make help — all common commands
├─ 00_README_MASTER.md … 09_RAG_MODULE.md   # design specs per workstream
└─ theft_detection/
   ├─ config/                # topology, hydro, sensors, scenarios, flags, RAG config
   ├─ grid/                  # Person 1: pandapower, cascade, hydro, search
   ├─ simdata/               # theft data (P4); cascade scenario export (P2)
   ├─ cascade_ml/            # Person 2: graph, predictor, calibration, screening, explanations
   │  ├─ graph.py
   │  ├─ predictor.py
   │  ├─ train.py
   │  ├─ calibration.py
   │  ├─ screening.py
   │  └─ explain.py          # scaffold entry points; not implemented yet
   ├─ loss_intelligence/     # Person 4: feeder and consumer loss workstream
   ├─ ml/                    # existing theft features, XGBoost, tap localization, evaluation
   ├─ contracts/             # versioned cross-person data and prediction handoffs
   ├─ rag/                   # RAG advisor (corpus of inspection playbooks, retriever, generator)
   ├─ vectordb/              # similar-case search over the feature embedding
   ├─ future/                # mitigation / load-balancing interfaces (stubs)
   ├─ backend/               # FastAPI app + tests
   ├─ frontend/              # React app, Vitest unit tests, Playwright e2e tests
   ├─ data/
   │  ├─ raw/                # baseline operating states
   │  ├─ processed/          # main dataset (parquet) + splits
   │  └─ models/             # trained models, metrics.json, sensor_study.json, gnn_results.json
   ├─ docs/                  # demo, ownership, progress, screenshots
   ├─ tests/                 # shared Python tests, grouped by workstream owner
   ├─ requirements.txt
   └─ docker-compose.yml
```

## Retraining from scratch

The repo ships with trained models, so this is optional. Run from `theft_detection/` (or use the `make`
target in brackets):

```bash
python -m simdata --profile major_only --seed 42 --n-jobs 8   # (make data)        dataset
python -m ml.train                                            # (make train)       all models + metrics.json
python -m ml.train --skip-gnn                                 # (make train-fast)  ~90 s, no GNN
python -m simdata.study_datasets --n-jobs 16 --skip-existing  # (make study-data)  12 study datasets, slow
python -m ml.sensor_study                                     # (make sensor-study)
python -m rag.ingest                                          # (make rag-index)   RAG advisor index
python -m vectordb.cases                                      # (make vector-index) similar-case index
```

The GNN trains 3 seeds on CPU and can take a few hours. The sensor-study datasets are about 350 MB and are not
committed to Git.

**Optional — LLM answers in the RAG advisor:** set `ANTHROPIC_API_KEY` in `.env`. Without a key, the advisor
works offline and answers with extracted, cited passages. Never commit a real key.

## Tests

```bash
cd theft_detection
python -m pytest tests                 # grid, simulation, ML, RAG, vector DB (124 tests)
cd backend && python -m pytest tests   # API (30 tests)
cd ../frontend && npm test             # React components (21 tests)
npx playwright test                    # full-stack browser tests (11 tests; starts API + web if not running)
```

## Assumptions & limitations

- The 5-substation chain and its distances (Sharavathi 0 km → Shimoga 110 → Sira/KB-Cross 215 → Nelamangala 320 →
  Peenya 361) are a **proposed simplified model**, not verified KPTCL/SLDC data. Edit `config/topology.yaml` when
  real data is available.
- Line parameters, loads and sensor noise (`config/sensors.yaml`) are **assumed** values.
- Results are from simulation only and have not been validated in the field. Thefts under about 5 MW sit close to
  the meter noise floor, and some neighbouring tap pairs cannot be told apart with only major-substation metering
  (see Sensor Study).
- Outputs use the wording *"suspected unauthorized extraction"*, never "theft confirmed".
- Load balancing / mitigation is **not implemented**. Only the interfaces and a locked UI tab exist.


