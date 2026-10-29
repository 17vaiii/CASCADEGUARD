# Team ownership and integration boundaries

This map uses the **Person 1 requirements in the CascadeGuard-Sharavathi PRD**
and the user-assigned Persons 2, 3, and 4 roles. The PDF numbers the platform
lead as Person 5; in this team map, the user's Person 3 (Optimization, RAG and
Full-Stack) is that platform workstream.

## Ownership map

| Owner | Owns these paths | Responsibilities and handoff |
|---|---|---|
| **Person 1 - Grid Simulation and Search (PRD P1)** | `grid/`, `config/topology.yaml`, `config/hydro.yaml`, `tests/test_person1_prd.py`, `docs/CORRIDOR_ASSUMPTIONS.md` | PRD R1, R10, H1, H3, H4, H5, H6 and P1-1 through P1-9: cascade simulator, corridor assumptions, seasonal and reservoir-constrained dispatch, topology variants, weak-link and attack search, weather outage weights, and renewable injections. Publishes the simulator contract consumed by the dataset generator and other workstreams. |
| **Person 2 - Cascade ML and Explainability (user P2)** | `cascade_ml/`, `config/cascade_ml.yaml`, `simdata/cascade_scenarios.py`, `tests/test_cascade_ml.py`, `tests/test_cascade_scenarios.py` | Graph builder, cascade GNN, calibration, fast N-k screening, explanations, and PRD R2 scenario orchestration/export. Consumes Person 1's simulator and publishes predictor outputs using `contracts/CASCADE_PREDICTION.md`. |
| **Person 3 - Optimization, RAG and Full-Stack (user P3; PDF platform P5)** | `backend/`, `frontend/`, `future/`, `rag/`, `vectordb/`, `backend/tests/`, `frontend/src/test/`, `frontend/e2e/` | Mitigation, closed-loop verification, operator interface, and RAG. Integrates through the API and handoff contracts; owns integration/release files such as `docker-compose.yml`, `Makefile`, and `backend/app/schemas.py`. |
| **Person 4 - Theft and Loss Intelligence (user/PDF P4)** | `loss_intelligence/`, theft-specific modules in `ml/`, `simdata/` except `simdata/cascade_scenarios.py`, `config/sensors.yaml`, `config/scenarios.yaml`, `tests/test_loss_intelligence.py` | Feeder loss, meter anomaly detection, suspicion reasons, inspection ranking, and T9 hidden-load estimate. Publishes the grid injection vector using `contracts/THEFT_LOAD_VECTOR.md`. |

## Existing files and conflict boundaries

The existing theft detector and tap-localization modules under `ml/` remain
Person 4-owned. Person 2 must put cascade prediction code in the new
`cascade_ml/` package; do not add cascade prediction code to `ml/gnn/`, which
already contains the theft tap localizer. Person 2 owns only
`simdata/cascade_scenarios.py`; Person 4 owns the theft scenario generator and
other existing `simdata/` modules.

The current `grid/cascade.py`, `grid/hydro.py`, `grid/attack_finder.py`, and
`simdata/cascade_scenarios.py` are existing work and may be untracked in Git.
Do not move them as part of parallel feature work: their import paths are
already used by the app and the generated data pipeline. Ownership is split
by module: Person 1 maintains the simulator and Person 2 maintains the cascade
dataset orchestration.

Person 1's PRD scope includes H5 weather overlays and H6 renewable
variability. Synthetic scenario inputs are implemented in `grid/weather.py`
and `grid/renewables.py`; they are not calibrated weather data or forecasts.
In the PRD's priority labels, H5 is P2
(stretch priority); that label is separate from its P1 ownership. H6 is P1
priority.

## Shared-file rules

1. Work in a branch per person, e.g. `codex/person1-grid`, `codex/person2-cascade-ml`,
   `codex/person3-platform`, and `codex/person4-loss`.
2. Keep changes within owned paths. If an interface change requires another
   owner's file, propose the change in the relevant contract first; the owning
   person applies it in their branch.
3. Treat `contracts/` as interface definitions. Person 3 integrates approved
   contract changes; other owners should not edit the same contract file in
   parallel. Record schema version changes in the contract's changelog.
4. Do not commit generated datasets, model checkpoints, `.env` files, or local
   logs unless the team explicitly requests those artifacts. Exchange data
   through the agreed local/shared artifact location and keep only cards or
   small fixtures in Git.
5. Merge in dependency order: Person 1 simulator contract, Person 2 consumer,
   Person 4 theft-load vector, then Person 3 integration. Rebase before opening
   a PR and ask the owner before editing a path assigned to someone else.

## PRD assignment note

The PRD assigns R2 cloud-parallel dataset infrastructure to its Person 2
cloud/data workstream, while the earlier user role list placed cascade Parquet
generation under Person 1. To keep Person 1 aligned with the PDF as requested,
this map assigns the *cascade dataset orchestration and export module*
`simdata/cascade_scenarios.py` to user Person 2, while Person 1 owns the
simulator and ground-truth physics it calls. Person 2 must preserve the
simulator's scenario schema and request simulator changes through Person 1.
