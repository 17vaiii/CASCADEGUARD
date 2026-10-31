# P2 local platform handoff

This is the local phase for PRD P2-3 through P2-9. Cloud accounts, object-store
provisioning, and cloud deployment are deferred. The data writers accept URI
destinations so the same pipeline can move to S3 or GCS by changing settings
and installing the corresponding fsspec driver.

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

For a cloud Ray cluster in the later phase, pass `--ray-address auto` or the
cluster address and set the output to an object-store URI, for example:

```bash
PYTHONPATH=src python -m cascadeguard.data.scenario_generator \
  --backend ray --ray-address auto \
  --output s3://<bucket>/cascadeguard/scenarios/cascade_dataset.parquet
```

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
seed for a sequential baseline and Ray. The report records elapsed seconds,
scenarios per hour, speedup, settings and whether Ray ran locally or on an
attached cluster. Until a cloud cluster exists, it reports local throughput;
that is not a cluster-vs-single-machine result. Run the same target with
`--ray-address <cluster>` later to collect the PRD comparison.

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
