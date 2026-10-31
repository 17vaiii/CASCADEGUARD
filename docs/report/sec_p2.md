<!-- OWNER: P2 | STATUS: LOCKED (until P1 handoff done) -->
# P2 — Local Data and Platform Foundation

**Owner:** Person 2 (Cloud, Data and Platform Lead)
**Status:** Local core implemented; cloud infrastructure and integrated model routes remain deferred.

## Architecture

The current phase runs in the project workspace. P1 cascade runs are exposed to
P2 through the existing simulator package and exported as labelled Parquet.
Scenario generation supports sequential, joblib, and Ray execution. Storage
uses local paths by default and an fsspec URI boundary for future S3/GCS use.
The companion synthetic interval-meter generator creates consumer and feeder
observations with ground-truth event classes for P4.

MLflow provides shared run tracking; Qdrant provides separate cascade-case,
theft-case, and document collections. The root FastAPI service packages in
Docker and publishes predict, screen, mitigate, and theft-score contracts. The
routes return explicit dependency-not-ready responses until their P3/P4/P5
model and optimizer handoffs are integrated. Recommendation records include
the advice, data references/fingerprint, and verification result in a local
SQLite audit store.

## Data and throughput

The meter generator writes interval-level Parquet containing a pseudonymous
consumer ID, feeder ID, consumer type, metered kWh, separately represented
unmetered feeder load, event window, tamper signal, and injected class. The
classes are meter bypass, meter stop, night tapping, hooking, and temporary
tampering, with a stable consumer-level train/validation/test split so
consumers do not cross evaluation splits. The row contract is in
`contracts/meter_data.schema.json`.

The benchmark compares identical single-machine sequential and Ray workloads
and records scenarios/hour plus speedup. It can target an attached Ray cluster,
but current local throughput numbers have not yet been collected in this
environment; cluster-vs-single-machine numbers require the deferred cloud
cluster. Use `make p2-benchmark` and retain its JSON output with the run.

## Experiment tracking and vector storage

Local Compose services persist MLflow metadata/artifacts and Qdrant data under
the workspace. Workstreams use `cascadeguard.common.tracking.tracked_run` and
the `cascadeguard-*` experiment naming convention. Qdrant's local collections
are `cascade_cases`, `theft_cases`, and `documents`; the default 128-dimensional
cosine vectors are configuration values to align with the embedding owners.

## Deployment boundary

Cloud resources are intentionally postponed. The configured seams are:

- storage URI plus fsspec drivers for S3/GCS;
- `RAY_ADDRESS` for a local or remote Ray runtime;
- MLflow tracking URI and artifact root;
- Qdrant URL and API key;
- audit database path now, database URL in the future.

Cloud account setup, access policies, cost caps, object-store provisioning,
cluster throughput, Cloud Run/ECS deployment, and cloud cost reporting belong
to the later phase. P2-10 streaming through Kafka/Pub/Sub remains a stretch
item. Full commands and the three-line handoff details are in
`docs/p2/local_platform_handoff.md`.
