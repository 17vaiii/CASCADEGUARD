# CascadeGuard main-package workflows. Python 3.12 is recommended.
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
PYTEST := $(PYTHON) -m pytest
PIP := $(PYTHON) -m pip

.PHONY: install install-dev test test-fast grid test-grid test-sim test-ml test-p4 test-p5 test-api data train api dashboard compose vector-index p2-install p2-meter-data p2-cascade-data p2-benchmark p2-platform p2-api p2-vector-init

install: ## Install main application dependencies
	$(PIP) install -r requirements.txt -r requirements-p5.txt

install-dev: install
	$(PIP) install black isort mypy

test: ## Run all main-package Python tests
	PYTHONPATH=src $(PYTEST) tests -q

test-fast: test

grid: test-grid

test-grid: ## Run corridor and cascade simulator tests
	PYTHONPATH=src $(PYTEST) tests/grid tests/sim -q

test-sim: ## Run scenario and data tests
	PYTHONPATH=src $(PYTEST) tests/data -q

test-ml: ## Run cascade ML tests
	PYTHONPATH=src $(PYTEST) tests/cascade_ml -q

test-p4: ## Run theft analytics tests
	PYTHONPATH=src $(PYTEST) tests/theft -q

test-p5: ## Run mitigation, retrieval and dashboard tests
	PYTHONPATH=src $(PYTEST) tests/mitigation tests/retrieval tests/dashboard -q

test-api: ## Run API tests
	PYTHONPATH=src $(PYTEST) tests/api -q

data: p2-meter-data p2-cascade-data ## Generate local meter and cascade datasets

train: ## Run P4 theft analytics pipeline
	PYTHONPATH=src $(PYTHON) -m cascadeguard.theft.pipeline

api: ## Start the main FastAPI application on :8000
	PYTHONPATH=src $(PYTHON) -m uvicorn cascadeguard.api.main:app --reload --port 8000

dashboard: ## Start the main Streamlit dashboard on :8501
	PYTHONPATH=src $(PYTHON) -m streamlit run src/cascadeguard/dashboard/app.py

compose: ## Start the local main-package services
	docker compose --profile local-platform up --build

vector-index: ## Load the main-package case collections into Qdrant
	PYTHONPATH=src $(PYTHON) -m cascadeguard.retrieval.load_qdrant --url http://localhost:6333

p2-install: ## Install P2 local pipeline/platform dependencies
	$(PIP) install -r requirements.txt

p2-meter-data: ## Generate synthetic interval-meter data
	PYTHONPATH=src $(PYTHON) -m cascadeguard.data.meter_generator --output data/processed/meter_readings.parquet

p2-cascade-data: ## Generate labelled N-1/N-2 cascade data with local Ray
	PYTHONPATH=src $(PYTHON) -m cascadeguard.data.scenario_generator --backend ray --workers 4 --k-max 2

p2-benchmark: ## Compare single-machine and Ray scenario throughput
	PYTHONPATH=src $(PYTHON) -m cascadeguard.data.benchmark_scenarios --k-max 2 --workers 4

p2-platform: ## Start local API, MLflow and Qdrant
	docker compose --profile local-platform up --build

p2-api: ## Run the main local API without Docker
	PYTHONPATH=src $(PYTHON) -m uvicorn cascadeguard.api.main:app --reload --port 8000

p2-vector-init: ## Create the local Qdrant collections
	PYTHONPATH=src $(PYTHON) -m cascadeguard.retrieval.load_qdrant --url http://localhost:6333