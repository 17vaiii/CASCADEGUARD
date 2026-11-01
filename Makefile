# Makefile — Sharavathi Corridor Theft Detection Project
# Requires: Python 3.12 (override with `make PYTHON=/path/to/python ...`), Node 20 for frontend

PYTHON ?= python
PYTEST := $(PYTHON) -m pytest
PIP    := $(PYTHON) -m pip

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
.PHONY: install install-dev
install:                  ## Install Python dependencies (CPU PyTorch + pinned requirements.txt)
	$(PIP) install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
	$(PIP) install -r theft_detection/requirements.txt

install-dev: install
	$(PIP) install black isort mypy

# ---------------------------------------------------------------------------
# WF1 — pandapower grid
# ---------------------------------------------------------------------------
.PHONY: grid grid-check grid-theft grid-baseline grid-viz

grid: grid-check           ## Build network and run sanity check

grid-check:                ## python -m grid.build --check
	cd theft_detection && $(PYTHON) -m grid.build --check

grid-theft:                ## Inject 20 MW theft at km 150 and check
	cd theft_detection && $(PYTHON) -m grid.build --check \
	    --theft-km 150 --theft-mw 20 --theft-pf 0.9

grid-baseline:             ## Generate data/raw/baseline_states.parquet (200 pts)
	cd theft_detection && $(PYTHON) -m grid.baseline --n 200

grid-viz:                  ## Generate diagnostic figures/ (voltage, loading, theft)
	cd theft_detection && $(PYTHON) -m grid.viz_check \
	    --save figures/ --theft-km 150 --theft-mw 20

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
.PHONY: test test-grid test-fast test-sim test-ml test-future test-rag test-vectordb rag-index

test: test-grid test-sim test-ml test-api test-future test-rag test-vectordb   ## Run all Python tests

test-sim:                  ## Run WF2 tests
	cd theft_detection && $(PYTEST) tests/test_simdata.py -v

test-vectordb:             ## Run local vector-DB tests
	cd theft_detection && $(PYTEST) tests/test_vectordb.py -v

test-rag:                  ## Run 09 RAG advisor tests (offline)
	cd theft_detection && $(PYTEST) tests/test_rag.py -v

rag-index:                 ## (09) Rebuild the RAG advisor index (data/models/rag_index.joblib)
	cd theft_detection && $(PYTHON) -m rag.ingest

test-future:               ## Run WF6 mitigation-stub contract tests
	cd theft_detection && $(PYTEST) tests/test_future.py -v

test-ml:                   ## Run WF3 tests (artifact tests need `make train`)
	cd theft_detection && $(PYTEST) tests/test_ml.py -v

test-grid:                 ## Run WF1 acceptance tests (tests/test_grid.py)
	cd theft_detection && $(PYTEST) tests/test_grid.py -v

test-fast:                 ## Run tests skipping the 100-scale convergence test
	cd theft_detection && $(PYTEST) tests/test_grid.py -v \
	    -k "not test_pf_100_random_scales"

# ---------------------------------------------------------------------------
# Placeholder targets for future workflows
# ---------------------------------------------------------------------------
.PHONY: data train train-fast train-gnn train-tune study-data sensor-study api test-api openapi dev compose vector-index web types test-web e2e all

data:                      ## (WF2) Generate synthetic dataset
	cd theft_detection && $(PYTHON) -m simdata --profile major_only --seed 42 --n-jobs 8

train:                     ## (WF3) Features, baseline, XGBoost, localizers, GNN (3 seeds), metrics.json
	cd theft_detection && $(PYTHON) -m ml.train

train-fast:                ## (WF3) Same without the GNN (~90 s)
	cd theft_detection && $(PYTHON) -m ml.train --skip-gnn

train-gnn:                 ## (WF3 step 5) GNN only (3 seeds) -> gnn.pt, gnn_results.json
	cd theft_detection && $(PYTHON) -m ml.gnn.train

train-tune:                ## (WF3) Same, with Optuna tuning (pip install optuna)
	cd theft_detection && $(PYTHON) -m ml.train --tune

study-data:                ## (WF3 step 6) Generate 3 profiles x 4 noise datasets (slow)
	cd theft_detection && $(PYTHON) -m simdata.study_datasets --n-jobs 16 --skip-existing

sensor-study:              ## (WF3 step 6) Retrain per profile/noise -> sensor_study.json
	cd theft_detection && $(PYTHON) -m ml.sensor_study

api:                       ## (WF4) Start FastAPI backend on :8000 (docs at /docs)
	cd theft_detection/backend && $(PYTHON) -m uvicorn app.main:app --reload --port 8000

test-api:                  ## (WF4) Backend tests
	cd theft_detection/backend && $(PYTEST) tests -v

openapi:                   ## (WF4) Export openapi.json for the frontend type generator
	cd theft_detection/backend && $(PYTHON) scripts/export_openapi.py

dev:                       ## (06) API :8000 + web :5173 with hot reload (Ctrl+C stops both)
	(cd theft_detection/backend && $(PYTHON) -m uvicorn app.main:app --reload --port 8000) & \
	(cd theft_detection/frontend && npm run dev)

compose:                   ## (06) docker compose up --build (api + web)
	cd theft_detection && docker compose up --build

vector-index:              ## (06/09) Rebuild the similar-case vector index
	cd theft_detection && $(PYTHON) -m vectordb.cases

web:                       ## (WF5) Start React dev server on :5173 (needs `make api`)
	cd theft_detection/frontend && npm run dev

types: openapi             ## (WF5) Regenerate TS API types from openapi.json
	cd theft_detection/frontend && npm run gen:types

test-web:                  ## (WF5) Vitest unit/component tests
	cd theft_detection/frontend && npm test

e2e:                       ## (WF5) Playwright smoke (starts api + web itself)
	cd theft_detection/frontend && npx playwright test

all: install grid-baseline grid-viz test
	@echo "WF1 complete. Proceed to WF2 (make data)."

# ---------------------------------------------------------------------------
# P2 platform work (local now; cloud adapter settings are in configs/platform)
# Run these with Python 3.12 and dependencies from requirements.txt installed.
# ---------------------------------------------------------------------------
.PHONY: p2-install p2-meter-data p2-cascade-data p2-benchmark p2-platform p2-api p2-vector-init

p2-install:                  ## Install root P2 pipeline/platform dependencies
	$(PIP) install -r requirements.txt

p2-meter-data:              ## Generate consumer interval data and five labelled injection types
	PYTHONPATH=src $(PYTHON) -m cascadeguard.data.meter_generator --output data/processed/meter_readings.parquet

p2-cascade-data:            ## Generate labelled N-1/N-2 cascade data with local Ray
	PYTHONPATH=src $(PYTHON) -m cascadeguard.data.scenario_generator --backend ray --workers 4 --k-max 2

p2-benchmark:               ## Compare single-machine and local/attached Ray throughput
	PYTHONPATH=src $(PYTHON) -m cascadeguard.data.benchmark_scenarios --k-max 2 --workers 4

p2-platform:                ## Start local API, MLflow and Qdrant
	docker compose --profile local-platform up --build

p2-api:                     ## Run local P2 API without Docker
	PYTHONPATH=src $(PYTHON) -m uvicorn cascadeguard.api.main:app --reload --port 8000

p2-vector-init:              ## Create cascade, theft and document collections in local Qdrant
	PYTHONPATH=src $(PYTHON) -m cascadeguard.retrieval.case_store

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.PHONY: help
help:                      ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	    awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

