# P2 agent context and continuation status

**Snapshot:** 2026-10-31, branch `sj`, implementation commit `32e1038` (`p2-3 to p2-10 tasks completed`).  
**Current task:** PRD Person 2 — Cloud, Data and Platform, local phase only.

Read this before changing P2 files. The attached PRD's P2 is the cloud/data
platform role. The `theft_detection/README.md` and
`theft_detection/docs/TEAM_OWNERSHIP.md` describe a separate, remapped demo-team
structure where Person 2 owns cascade ML. Keep those roles distinct. This
handoff documents the PRD P2 implementation in the root `src/cascadeguard/`
package and its interfaces to the existing cascade simulator in
`theft_detection/`.

## Project map relevant to P2

- `src/cascadeguard/data/`: local-first Parquet storage, meter generation,
  cascade-generation adapter, throughput benchmark.
- `src/cascadeguard/common/`: fsspec-aware file writers and shared MLflow helper.
- `src/cascadeguard/retrieval/case_store.py`: Qdrant adapter for three collections.
- `src/cascadeguard/api/`: FastAPI contracts and SQLite recommendation audit.
- `configs/platform/local.yaml`: local defaults and cloud integration seams.
- `configs/cloud/ray_cluster.yaml`: future Ray/cloud placeholders; no credentials
  or provisioned cloud resources belong here.
- `docker-compose.yml`, `docker/Dockerfile.api`,
  `docker/Dockerfile.mlflow`: local API, tracking server, and Qdrant services.
- `contracts/`: P2 API, scenario, and meter data contracts.
- `docs/p2/local_platform_handoff.md`: exact commands and sample handoff records.
- `docs/report/sec_p2.md`: report draft. Replace pending statements with measured
  results only after running the pipeline.

## P2 task status

| PRD task | Implemented in code/config | Still needed |
|---|---|---|
| **P2-3** Ray scenario pipeline | `theft_detection/simdata/cascade_scenarios.py` supports sequential, joblib, and Ray; root adapter writes labelled Parquet and accepts output URIs. | Install runtime dependencies; generate a fresh root artifact and verify its schema. Do not overwrite the existing demo artifact under `theft_detection/data/processed/`. |
| **P2-4** throughput | `src/cascadeguard/data/benchmark_scenarios.py` compares sequential with Ray and writes JSON; it logs a run to MLflow when reachable. | Run locally first. Cluster-versus-single-machine numbers require the later Ray cluster. Record actual results in `docs/report/sec_p2.md`. |
| **P2-5** meter data | `src/cascadeguard/data/meter_generator.py` emits five injected classes, normal rows, hidden feeder load separately from meter readings, and consumer-level train/validation/test splits. | Generate Parquet and inspect class counts/schema; pass artifact and card to P4. |
| **P2-6** tracking | Local MLflow Compose service and `cascadeguard.common.tracking.tracked_run` helper. Throughput benchmark records metrics/run link if server is reachable. | Start service, log a smoke experiment and provide its local link; have P3/P4/P5 use the helper. No experiment link exists yet. |
| **P2-7** vector database | Local Qdrant Compose service, adapter, and initializer for `cascade_cases`, `theft_cases`, `documents`. | Start Qdrant and run `make p2-vector-init`. Confirm/coordinate vector dimensions (default 128) with P3/P4/P5 before ingesting. |
| **P2-8** API | Docker packaging and routes for `/api/predict`, `/api/screen`, `/api/mitigate`, `/api/theft-score`; OpenAPI contract provided. | Runtime-test API. The four model routes deliberately return 503 until P3/P4/P5 register their implementations. This is an integration dependency, not a working model response. Cloud deployment is deferred. |
| **P2-9** audit | SQLite create/read/update-verification implementation and API routes; stores advice, references/fingerprint, verification, and timestamp. | HTTP-test full audit lifecycle. Integrate every future recommendation-producing route with the audit call. No raw meter payload should be stored. |
| **P2-10** streaming | Not implemented. | Stretch item; defer unless core tasks are complete and schedule allows. Existing demo WebSocket replay is not Kafka/Pub/Sub scoring. |

## Validation actually completed

The prior verification checked Python syntax compilation, YAML and JSON
parsing, static route-to-OpenAPI path agreement, a SQLite audit create/verify/
read lifecycle, and whitespace (`git diff --check`). These passed after fixing
malformed YAML in `contracts/openapi.yaml`.

Runtime validation is outstanding. The active Python environment lacked
FastAPI, Pydantic, pandas, PyArrow, pandapower, Ray, MLflow, and `qdrant-client`;
Docker was unavailable. Consequently, no HTTP endpoint, Docker image/service,
Ray task, Parquet generation, MLflow UI, or Qdrant collection was exercised.
No project pytest suite was run. Do not describe P2 runtime behavior as
verified until these checks pass.

## Recommended continuation order

1. Inspect `git status` first. During the original P2 session,
   `theft_detection/data/models/case_index.joblib` and
   `theft_detection/data/models/rag_index.joblib` were already modified before
   P2 work; they are clean at this documentation snapshot. Preserve any future
   local changes and do not rebuild model indexes without the owner's direction.
2. Install the root platform stack with `make p2-install`.
3. Start local services with `make p2-platform`, then initialize the vector
   collections with `make p2-vector-init`.
4. In a separate terminal, run `make p2-meter-data` and
   `make p2-cascade-data`. Outputs go under ignored root `data/processed/` paths.
5. Run `make p2-benchmark`. It currently compares sequential and local Ray;
   collect this before attaching a cloud Ray cluster. For the later cluster run,
   invoke `PYTHONPATH=src python -m cascadeguard.data.benchmark_scenarios
   --output-dir data/processed/throughput --k-max 2 --workers 4
   --ray-address auto` directly (Make does not forward benchmark arguments).
6. HTTP-check `/health`, audit create/verify/read, and confirm model endpoints
   return the documented 503 until their owners integrate the predictor,
   screening, optimizer, and theft model. Then run relevant Python tests and
   API tests; update the verification status and report with observed results.
7. Keep account creation, buckets, cloud credentials, cluster provisioning,
   Cloud Run/ECS deployment, and cost measurements in the later cloud phase.

## Handoff safety and interfaces

- Root generated Parquet, local Qdrant storage, audit DB, and MLflow files are
  ignored by Git. The checked-in demo cascade artifact remains in its existing
  `theft_detection/` path.
- Meter rows follow `contracts/meter_data.schema.json`; cascade rows follow
  `theft_detection/contracts/CASCADE_SCENARIOS.md` and include pre-contingency
  graph features. Never use the post-cascade wide loading/voltage columns as
  predictor inputs.
- API endpoints and audit payloads follow `contracts/openapi.yaml`. Shared
  contract changes need review from the integration owner.
- S3/GCS URIs use fsspec drivers and provider credentials. Ray, MLflow, Qdrant,
  and audit destinations are configurable; cloud placeholders are not live
  infrastructure.
- See root `README.md` for project overview and `theft_detection/README.md` for
  the imported demo's separate runtime/progress snapshot.
