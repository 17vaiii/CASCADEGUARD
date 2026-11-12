# P2 agent context and continuation status

**Scope:** PRD Person 2 â€” Cloud, Data and Platform. The main package lives in `src/cascadeguard/`.

## Project map

- `src/cascadeguard/data/`: local-first Parquet storage, meter generation, cascade generation, throughput benchmark.
- `src/cascadeguard/data/cascade_sim/`: migrated cascade simulator adapter and scenario generation support.
- `src/cascadeguard/common/`: fsspec-aware file writers and shared MLflow helper.
- `src/cascadeguard/retrieval/case_store.py`: Qdrant adapter for three collections.
- `src/cascadeguard/api/`: FastAPI contracts and SQLite recommendation audit.
- `configs/platform/local.yaml` and `configs/cloud/ray_cluster.yaml`: local defaults and future cloud placeholders.
- `docker-compose.yml` and `docker/`: local API, tracking server, and Qdrant services.
- `contracts/`: P2 API, scenario, and meter data contracts.

## Current commands

Install with `make p2-install`; generate interval-meter and cascade datasets with `make p2-meter-data` and `make p2-cascade-data`; benchmark with `make p2-benchmark`. Outputs are under root `data/processed/`.

The cascade generator uses only the main package and writes the pre-contingency graph features described by `contracts/CASCADE_SCENARIOS.md` and `contracts/scenario_record.schema.json`. Ray workers use the project root as their working directory and `PYTHONPATH=src`.

Cloud accounts, object-store provisioning, remote Ray, and Cloud Run/ECS deployment remain deferred. The local stack uses Docker Compose, MLflow, Qdrant, and FastAPI.

## Boundaries

- Cloud storage and remote Ray are configured for later use and have not been exercised without infrastructure.
- Kafka/Pub/Sub streaming remains a stretch item.
- The API routes follow `contracts/openapi.yaml`; model routes return a dependency-not-ready response until their model components are available.
- Meter rows follow `contracts/meter_data.schema.json`; do not store raw meter payloads in the audit database.