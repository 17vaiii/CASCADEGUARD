# P2 local platform handoff

This handoff covers the PRD Person 2 local data and platform work in the main
`src/cascadeguard/` package. Cascade simulation and scenario generation are
available locally through `src/cascadeguard/data/cascade_sim/` and the P2 data
commands. Cloud accounts, object storage, remote Ray, and deployment remain
deferred.

## Start locally

Install dependencies with `make p2-install`, then generate datasets:

```bash
make p2-meter-data
make p2-cascade-data
```

The meter and cascade outputs are written under root `data/processed/`. The
cascade dataset follows [CASCADE_SCENARIOS.md](../../contracts/CASCADE_SCENARIOS.md)
and [scenario_record.schema.json](../../contracts/scenario_record.schema.json).
Pre-contingency graph features are model inputs; final-state wide loading and
voltage columns are diagnostics only.

Start local services with `make p2-platform`. The API is at port 8000, MLflow at
port 5000, and Qdrant at port 6333. Use `make p2-vector-init` to initialize the
case and document collections.

## Throughput and tracking

`make p2-benchmark` compares the same workload using sequential generation and
Ray. Until a remote cluster is available, both runs are local. The report
records attempted and written rows, elapsed time, scenarios per hour, speedup,
settings, and MLflow tracking status.

For an attached cluster, run `cascadeguard.data.benchmark_scenarios` with
`--ray-address auto`. S3/GCS output requires the matching fsspec driver and
provider credentials. Do not put credentials in repository configuration.

## API and audit

Contracts live in `contracts/openapi.yaml`. The API stores recommendation
metadata, data references or fingerprints, and verification results in the
local audit database; it does not store raw meter payloads.

## Verification boundaries

- Local sequential and Ray generation are supported; remote cluster execution
  and cloud object storage are not verified here.
- Cloud Run/ECS deployment and Kafka/Pub/Sub telemetry remain deferred.
- Model endpoints may return dependency-not-ready responses until their model
  components are registered.