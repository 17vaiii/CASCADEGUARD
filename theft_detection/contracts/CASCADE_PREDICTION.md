# Cascade prediction contract

**Producer:** Person 2 cascade ML. **Consumer:** Person 3 platform and
verification. Predictions must identify the scenario or network snapshot and
must not be presented as verified outcomes until checked by the simulator.

Required logical fields:

- `scenario_id` or `snapshot_id`: input identity.
- `line_failure_probabilities`: mapping of line ID to probability in [0, 1].
- `predicted_cascade_size`: non-negative integer or count estimate.
- `predicted_load_lost_mw`: non-negative corridor load-loss estimate.
- `predicted_bengaluru_load_lost_mw`: non-negative Bengaluru endpoint estimate.
- `confidence`: calibration metadata, including stated coverage level and
  interval bounds where applicable.
- `model_version`: model/checkpoint identity.

Person 2 owns the wire format and model artifacts. Person 3 owns API schema
changes needed to expose them. Keep explanatory paths/critical lines as an
optional field so an inference-only response remains valid.

Scenario embeddings may also be returned as an optional `scenario_embedding`
field for Person 3's retrieval and visualization work.

## Changelog

- v1: Initial prediction and embedding handoff contract.
