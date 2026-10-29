# Cascade ML - Person 2

Person 2 owns cascade-specific graph data, GNN training/inference, calibration,
fast N-k screening, and explanation code in this package. Keep these modules
separate from `ml/`, which contains the existing Person 4 theft detection and
tap-localization pipeline.

## Module map

- `graph.py` - R3 snapshot-to-graph conversion and feature schema.
- `predictor.py` - R4 per-line risk, cascade extent, and load-loss prediction.
- `train.py` - R4 training, validation, and versioned checkpoint output.
- `calibration.py` - R5 probability calibration and conformal intervals.
- `screening.py` - R6 fast N-k candidate ranking for Person 1 validation.
- `explain.py` - R7 critical-line and cascade-path explanations.

These are scaffolds only; each entry point currently raises
`NotImplementedError`. Add implementation and owned tests as each task starts.

Read `contracts/CASCADE_SCENARIOS.md` for the simulator dataset input and
`contracts/CASCADE_PREDICTION.md` for the platform output. Do not edit `grid/`
or the theft `ml/` pipeline; request interface changes through the owning
person and contract.
