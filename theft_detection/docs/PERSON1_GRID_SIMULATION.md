# Person 1 - Grid Simulation and Hydro Handoff

This note maps work to **Person 1 in the product PRD**: R1, R10, H1, H3, H4,
H5, and H6. The model is a synthetic corridor, not a verified KPTCL network;
values marked `assumed` remain assumptions until validated against operator
data. See `docs/TEAM_OWNERSHIP.md` for file ownership and handoffs.

## Delivered in the project

- `grid/benchmarks.py`: repeatable IEEE 14/39/118 AC benchmarks; all converge
  in the current environment. This validates the solver, not corridor data.
- `grid/cascade.py`: dual-circuit corridor construction, initial N-k trips,
  island detection and load shedding, AC re-solves, iterative overload trips,
  cascade trace, and final labels including `failed_lines` and
  `bengaluru_load_lost_mw` (PEENYA is the Bengaluru endpoint in this topology).
- `grid/hydro.py` and `config/hydro.yaml`: monsoon, post-monsoon, and summer
  scenario profiles; Linganamakki turbine, ramp, daily-energy, inflow, and
  minimum-reservoir constraints through `dispatch_hydro` and explicit per-day
  `HydroDispatchState`. `simulate_hydro_day` evaluates a chronological day.
  Seasonal cascade cases inject bounded hydro at
  Sharavathi and balance imports at the assumed SHIMOGA grid tie, so dispatch
  changes corridor flows.
- `grid/attack_finder.py`: greedy and beam N-k search, minimum-k target search,
  and a GNN scorer adapter. The adapter uses the model to guide candidates but
  verifies each returned finalist using the AC simulator. Ranking uses Bengaluru
  load loss when the topology has a PEENYA/BENGALURU endpoint. The seasonal
  weak-link report ranks single-line outages independently for each season.
- `simdata/cascade_scenarios.py` is the PRD R2 dataset generator and is owned
  by Person 2. It calls Person 1's simulator and exports deterministic
  N-1/N-2/N-3 scenarios with failed lines, load loss, affected buses, and
  hydro/season metadata.
- `grid/topology_variants.py` generates seeded corridor-like 30–60 bus cases.
  `grid/weather.py` supplies synthetic weather-weighted outage priors, and
  `grid/renewables.py` supplies seasonal solar/wind profiles and injections.
  These are explicitly assumed scenario inputs.

## Running the handoff generators

From `sharavathi-theft/`:

```powershell
python -m grid.build --check
python -m simdata.cascade_scenarios --k-max 2 --jobs 4
python -m grid.attack_finder --out data/processed/weak_link_report.parquet `
  --attack-dataset data/processed/cascade_dataset.parquet
```

The cascade dataset is written to `data/processed/cascade_dataset.parquet`.
`--k-max 3` includes N-3 and may require substantially more runtime. The
seasonal weak-link report is written to
`data/processed/weak_link_report.parquet` (or pass a `.csv` output path).
The same command ranks the simulated contingencies per season and writes
`data/processed/attack_report.parquet`.

## Scope and limitations

The PRD's general requirement calls for a corridor shaped like the real system,
not a claimed replica. The checked-in topology has five named substations and
virtual tap buses at 10 km intervals. Seasonal demand scaling is applied to
all corridor loads; summer therefore represents higher Bengaluru demand in the
reduced model. Each contingency is an independent operating snapshot; the
dataset does not simulate a chronological 24-hour dispatch trajectory. The
SHIMOGA import tie and all hydro parameters are assumed representations, not
verified grid assets or operating limits. Public-source limitations are recorded
in `docs/CORRIDOR_ASSUMPTIONS.md`. GNN-guided search is ready for P2's scorer;
end-to-end predictive performance depends on that model being implemented.

The PRD assigns R2 dataset infrastructure to its Person 2 data/platform
workstream. To keep Person 1 aligned with the PDF, Person 1 owns the grid
simulation and ground-truth physics while Person 2 owns the cascade dataset
orchestration and ML consumer. The provided user role calls Person 2 the
Cascade ML lead; this map assigns R2 there as the closest matching workstream.
