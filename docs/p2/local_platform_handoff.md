# P2 local platform handoff

This handoff covers the **Cloud, Data and Platform P2 role in the attached
PRD**, specifically P2-3 through P2-9. The separate `theft_detection/` demo
docs use a remapped team role where Person 2 owns cascade ML. For the current
PRD P2 work, the platform implementation lives primarily under `src/cascadeguard/`
and its Make targets; `theft_detection/simdata/cascade_scenarios.py` supplies
the existing P1 engine adapter. See [agent_context.md](agent_context.md) before
continuing.

Cloud accounts, object-store provisioning, a Ray cluster, and deployment are
deferred to a later phase. Current defaults use local files and services. Data
writers accept URI destinations so the same pipeline can move to S3 or GCS by
changing the destination and installing the corresponding fsspec driver.

## Start locally

Install the root P2 dependencies with `make p2-install` (or
`python -m pip install -r requirements.txt`).
The root modules are run with `PYTHONPATH=src` (or from the Makefile targets).

```bash
make p2-meter-data
make p2-cascade-data
```

Start the local services in one terminal, then run the benchmark in another so
the report and throughput metrics are logged to MLflow:

```bash
# Terminal 1
make p2-platform
# Terminal 2
make p2-benchmark
```

The meter file defaults to `data/processed/meter_readings.parquet`. Cascade
generation writes `data/processed/cascade_dataset.parquet`, keeping this P2
output separate from the existing checked-in demo artifact under
`theft_detection/data/processed/`.
The benchmark writes the sequential and Ray datasets plus
`data/processed/throughput/throughput_benchmark.json`. If MLflow is reachable,
the report also includes a run URL and the JSON report is logged as an artifact.

For the later cluster comparison, `make p2-benchmark` cannot forward CLI
arguments. Invoke the module directly and provide the Ray cluster address. The
sequential baseline runs on the submitting machine; the Ray workload runs on
the attached cluster:

```bash
PYTHONPATH=src python -m cascadeguard.data.benchmark_scenarios \
  --output-dir data/processed/throughput --k-max 2 --workers 4 \
  --ray-address auto
```

For a one-sided cluster data-generation run, call
`cascadeguard.data.scenario_generator` with `--backend ray --ray-address auto`
and set `--output` to an object-store URI.

For GCS use `gs://...` and install `gcsfs`; for S3 install `s3fs`. Credentials
must come from the cloud workload identity or local provider credential chain,
not checked-in configuration.

## Handoff schemas

The meter record contract is [meter_data.schema.json](../../contracts/meter_data.schema.json).
It provides synthetic consumer and feeder IDs, interval kWh, an event window,
the injected class (`meter_bypass`, `meter_stop`, `night_tapping`, `hooking`,
`temporary_tampering`, or `none`), and `is_suspected_loss`. Unmetered load is
recorded separately in `feeder_unmetered_kwh`; it is never added to a consumer's
meter reading. Cascade scenario rows follow
[CASCADE_SCENARIOS.md](../../theft_detection/contracts/CASCADE_SCENARIOS.md).

Example meter input/configuration:

```json
{"consumers": 250, "days": 60, "interval_minutes": 60, "theft_fraction": 0.25, "seed": 42}
```

Representative output row:

```json
{"timestamp":"2025-01-03T22:00:00Z","consumer_id":"C0000001","feeder_id":"F001","consumer_type":"residential","metered_kwh":0.42,"feeder_unmetered_kwh":0.0,"is_event":true,"is_suspected_loss":true,"theft_type":"meter_bypass","event_start":"2025-01-03T00:00:00Z","event_end":"2025-01-08T23:00:00Z","tamper_event":false,"scenario_seed":42,"split":"train"}
```

## Throughput and tracking

`make p2-benchmark` uses identical seasons, contingency sizes, load scales and
seed for a sequential baseline and Ray. The report records attempted and
written row counts, elapsed seconds, scenarios per hour, speedup, settings,
execution scope, and MLflow tracking status/link. Until a cloud cluster exists,
the report is a local single-machine-versus-local-Ray comparison, not the
PRD's cluster-versus-single-machine result.

`make p2-platform` starts FastAPI, MLflow and Qdrant. MLflow is at
`http://localhost:5000`; experiment code should use
`cascadeguard.common.tracking.tracked_run` and the `cascadeguard-*` experiment
names. Qdrant is at `http://localhost:6333`. Run `make p2-vector-init` once to
create `cascade_cases`, `theft_cases` and `documents`. Their default vector
size is 128; coordinate a dimension change with the embedding producers before
loading P3/P4/P5 data.

## API and audit handoff

`make p2-api` runs the API on port 8000, with OpenAPI at `/docs`. Contracts are
`/api/predict`, `/api/screen`, `/api/mitigate` and `/api/theft-score`. They
return an explicit 503 until the dependent P3/P4/P5 implementation is
registered; the API does not fabricate model answers. Recommendation audit
records persist locally in `data/audit/recommendations.sqlite3`, with
recommendation, data references/fingerprint and a later verification result.
No raw meter payload is placed in the audit store.

Example audit request:

```json
{"recommendation":{"action":"inspect feeder F001"},"data_refs":["scenario-123"],"data_fingerprint":"sha256:..."}
```

The generated `audit_id` is used to submit a verification result through
`POST /api/audit/recommendations/{audit_id}/verification`.

## Verification status (2026-10-31)

Static checks passed: Python syntax compilation for changed modules, YAML and
JSON parsing, API path inventory matched to OpenAPI, SQLite audit
create/verify/read, and `git diff --check`. No HTTP server, Docker build, Ray
job, meter dataset, Parquet generation, or throughput benchmark was run. At
that check the active Python environment did not have FastAPI, Pydantic,
pandas, PyArrow, pandapower, Ray, MLflow, or `qdrant-client`; Docker was also
unavailable. Install dependencies and repeat runtime checks before marking
these components operational. The project test suite was not run.

## Current boundaries

- Ray code supports local and attached runtimes; no cloud cluster was created.
- S3/GCS writers are configured through fsspec but were not exercised without
  cloud credentials and the deferred infrastructure.
- API Docker packaging and local compose services are provided. Cloud Run/ECS
  deployment remains deferred, as requested.
- Cascade prediction/screening, mitigation and theft-score routes remain
  dependency-gated until P3/P4/P5 publish their implementations.
- P2-10 Kafka/Pub/Sub telemetry is still a stretch item and is not part of this
  core local phase. Existing demo WebSocket replay is separate.
