# Cascade scenario contract

**Producer:** Person 1 grid simulator. **Consumers:** Person 2 cascade ML and
Person 3 verification/API. **Format:** Parquet, one row per operating point
and initial contingency. Keep nested lists as Arrow list columns.

## Required columns

| Column | Type | Meaning |
|---|---|---|
| `scenario_id` | string | Stable unique ID for season, load scale, k and initial trips. |
| `seed` | int | Seed used by the scenario generation job. |
| `season` | string | `monsoon`, `post_monsoon`, or `summer`. |
| `load_scale` | float | Additional multiplier applied to seasonal corridor demand. |
| `contingency_k` | int | Number of initially tripped lines (N-k). |
| `initial_trips` | list[int] | Line indices tripped at time zero. |
| `initial_trip_names` | list[string] | Stable human-readable initial line IDs. |
| `failed_lines` | list[int] | All initially and subsequently tripped line indices. |
| `failed_line_names` | list[string] | Names corresponding to `failed_lines`. |
| `affected_buses` | list[int] | Buses whose loads were disconnected or unserved. |
| `cascade_depth` | int | Number of cascade solve/trip iterations. |
| `load_lost_mw` | float | Total corridor load not served at the final state. |
| `bengaluru_load_mw` | float | Bengaluru endpoint demand in the scenario. |
| `bengaluru_load_lost_mw` | float | Unserved Bengaluru endpoint demand. |
| `bengaluru_load_shed_pct` | float | Percent of Bengaluru demand unserved, 0-100. |
| `bengaluru_blackout` | bool | True when the Bengaluru endpoint demand is fully unserved. |
| `converged` | bool | Whether final AC power flow converged. |

Additional fields may include per-line loadings, bus voltages, served load,
islanding, hydro dispatch, reservoir state, and losses. Additions must not
change the meaning of required fields. `failed_lines` must include the initial
trips; `cascade_depth` must not count the initial trip as a solve iteration.

## Graph features and label timing

`graph_feature_schema = cascade_graph_v1` identifies the pre-contingency graph
features used by Person 2. In that schema:

- `bus_ids`, `pre_bus_vm_pu`, `pre_bus_p_mw`, and `pre_bus_q_mvar` are aligned
  lists in bus order.
- `line_ids`, `line_names`, `line_from_bus`, `line_to_bus`,
  `pre_line_r_ohm`, `pre_line_x_ohm`, and `pre_line_loading_pct` are aligned
  lists in line order. Endpoints refer to indices in `bus_ids`.
- `graph_feature_timing` must equal `pre_contingency`; these are the valid
  predictor inputs.

Legacy wide columns `line_<id>_loading` and `bus_<id>_vm_pu` are final-state
outcomes after the cascade. Treat them as diagnostics only; using them as
predictor inputs leaks outcome information. Outcome labels include
`failed_lines`, `cascade_depth`, `load_lost_mw`, and
`bengaluru_load_lost_mw`.

## Current artifact

`data/processed/cascade_dataset.parquet` is a generated local artifact and is
not a source-controlled interface. Regenerate it from code when the simulator
or contract changes. Document generation settings and assumptions in the
dataset card or run manifest.

## Changelog

- v1: Initial contract aligned with the current cascade scenario generator.
- v2: Add ordered, pre-contingency graph features and explicitly mark legacy
  wide voltage/loading columns as post-cascade diagnostics.
