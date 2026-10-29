# Cascade dataset card

## Current local artifact

`data/processed/cascade_dataset.parquet` contains 8,778 simulated scenarios:

- 2,926 per season: monsoon, post-monsoon, summer.
- 228 N-1 and 8,550 N-2 rows; all 8,778 scenario IDs are unique.
- 39 buses and 76 dual-circuit line edges in each graph snapshot.
- All rows in the checked artifact converged in the final AC power flow.
- No N-3 rows are present.

## Person 2 inputs

The `cascade_graph_v1` fields are ordered arrays. `graph_feature_timing` is
`pre_contingency` for every row. Bus inputs are `bus_ids`, `pre_bus_vm_pu`,
`pre_bus_p_mw`, and `pre_bus_q_mvar`. Line inputs are `line_ids`,
`line_names`, `line_from_bus`, `line_to_bus`, `pre_line_r_ohm`,
`pre_line_x_ohm`, and `pre_line_loading_pct`. Array positions align by their
bus or line ID fields; line endpoints use bus indices.

Use scenario context including `season`, `load_scale`, and `initial_trips` as
additional inputs. Outcomes include `failed_lines`, `cascade_depth`,
`load_lost_mw`, `bengaluru_load_lost_mw`, `blackout`, and `converged`.

Legacy wide `line_<id>_loading` and `bus_<id>_vm_pu` columns are final-state
diagnostics. Do not use them as model inputs because they contain post-event
information. See `contracts/CASCADE_SCENARIOS.md` for the versioned interface.

## Provenance and limitations

The scenarios use the assumed corridor and hydro parameters documented in
`docs/CORRIDOR_ASSUMPTIONS.md`. They are synthetic research outputs, not actual
grid telemetry or verified utility operating conditions. Renewable and weather
overlays are not yet included in this artifact. The artifact is a local generated
file; regenerate it using `python -m simdata.cascade_scenarios --k-max 2` after
changing the scenario generator or the simulator.
