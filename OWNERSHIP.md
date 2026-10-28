<!-- OWNER: P1 | STATUS: ACTIVE -->
# OWNERSHIP.md: Role-to-Folder Mapping

This file defines the strict file and folder ownership across the 5 project roles for CascadeGuard-Sharavathi.

## Roles Overview
- **P1: Grid Simulation and Search Lead** (Critical path, currently active)
- **P2: Cloud, Data and Platform Lead**
- **P3: Cascade ML Lead**
- **P4: Theft and Loss Analytics Lead**
- **P5: Optimization, RAG, LLM and Dashboard Lead**

## Mapping Table

| Path / Pattern | Owner | Needs | Notes / Status |
|---|---|---|---|
| `.agent/role` | P1 | - | Active role ("P1") |
| `.agent/rules/ownership.md` | P1 | - | Active ownership rules |
| `OWNERSHIP.md` | P1 | - | Folder mapping |
| `scripts/` | P1 | - | Pre-commit check, scaffold |
| `configs/grids/` | P1 | - | IEEE 14/39/118, corridor_v0 |
| `configs/seasons/` | P1 | - | Seasonal profiles |
| `configs/hydro/` | P1 | - | Hydro limits & storage |
| `src/cascadeguard/__init__.py` | P1 | - | Package init |
| `src/cascadeguard/grid/` | P1 | - | Grid loaders, corridor, hydro |
| `src/cascadeguard/sim/` | P1 | - | Cascade engine, contingency |
| `tests/__init__.py` | P1 | - | Test root |
| `tests/grid/` | P1 | - | Grid tests |
| `tests/sim/` | P1 | - | Simulation tests |
| `notebooks/` | P1 | - | Exploratory power flow |
| `docs/p1/` | P1 | - | Assumptions, specs, handoffs, sources |
| `docs/report/sec_p1.md` | P1 | - | Report section P1 |
| `docs/results_table.md` | ALL | - | Shared results table |
| `README.md`, `pyproject.toml`, `requirements.txt` | P2 | - | Locked |
| `.gitignore`, `.env.example`, `Makefile`, `CODEOWNERS` | P2 | - | Locked |
| `.github/` | P2 | - | Locked |
| `contracts/grid_snapshot.schema.json` | P2 | P1 | Locked |
| `contracts/scenario_record.schema.json` | P2 | P1 | Locked |
| `contracts/meter_data.schema.json` | P2 | - | Locked |
| `contracts/openapi.yaml` | P2 | P3,P4,P5 | Locked |
| `configs/cloud/` | P2 | - | Locked |
| `configs/theft/theft_injection.yaml` | P2 | - | Locked |
| `src/cascadeguard/common/` | P2 | - | Locked |
| `src/cascadeguard/data/` | P2 | P1 | Locked |
| `src/cascadeguard/api/` | P2 | P3,P4,P5 | Locked |
| `tests/data/`, `tests/api/` | P2 | - | Locked |
| `experiments/`, `data/`, `docker/Dockerfile.api` | P2 | - | Locked |
| `docs/report/sec_p2.md` | P2 | - | Locked |
| `contracts/graph_tensor_format.md` | P3 | P2 | Locked |
| `configs/model/` | P3 | P2 | Locked |
| `src/cascadeguard/cascade_ml/` | P3 | P1,P2 | Locked |
| `tests/cascade_ml/` | P3 | - | Locked |
| `docs/report/sec_p3.md` | P3 | - | Locked |
| `configs/theft/models.yaml` | P4 | P2 | Locked |
| `src/cascadeguard/theft/` | P4 | P1,P2,P3 | Locked |
| `tests/theft/` | P4 | - | Locked |
| `docs/report/sec_p4.md` | P4 | - | Locked |
| `configs/mitigation/` | P5 | P1 | Locked |
| `src/cascadeguard/mitigation/` | P5 | P1 | Locked |
| `src/cascadeguard/retrieval/` | P5 | P2,P3 | Locked |
| `src/cascadeguard/copilot/` | P5 | - | Locked |
| `src/cascadeguard/dashboard/` | P5 | P2,P3,P4 | Locked |
| `docker/Dockerfile.dashboard` | P5 | P2 | Locked |
| `tests/mitigation/`, `tests/retrieval/`, `tests/dashboard/` | P5 | - | Locked |
| `docs/report/sec_p5.md` | P5 | - | Locked |
