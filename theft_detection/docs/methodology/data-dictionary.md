# Data dictionary

All identifiers are synthetic. Arrays are indexed `[entity, hour]`, with hour 0 = start of the
28-day history and `h0 = 672` = timeline step 0.

## Identifiers

| Pattern | Meaning |
|---|---|
| `F1`…`F6` | 11 kV feeder |
| `F2-DT3` | Distribution transformer 3 on feeder F2 |
| `C-F2-DT3-009` | Consumer 9 supplied by F2-DT3 (synthetic, corresponds to no real person) |
| `GRID220`, `HYD220`, `TXA220`, `SRS220`, `SRS66`, `DSS66`, `DSS11`, `OTHER66` | Buses of the illustrative upstream network |
| `F2J1` | 11 kV tapping point (pole) on F2 |

## SimulationData (`simulation/generator.py`)

| Field | Shape | Unit | Description |
|---|---|---|---|
| `true_kwh` | C×H | kWh/h | Energy actually drawn by each consumer |
| `recorded_kwh` | C×H | kWh/h | Energy the meter registers before measurement error (differs under B/D) |
| `meter_kwh` | C×H | kWh/h | Ingested reading after meter error and de-duplication; NaN = never received |
| `arrival_delay` | C×H | h | Hours after the interval until the reading arrives; ∞ = never |
| `unmetered_kw` | DT×H | kW | Simulated unmetered load (Scenario C) |
| `energised` | F×H | bool | Feeder supplied (false during outages) |
| `feeder_true_kwh`, `feeder_meter_kwh` | F×H | kWh/h | Feeder-head energy, true / metered (NaN = missing) |
| `dt_true_kwh`, `dt_meter_kwh` | DT×H | kWh/h | DT secondary energy, true / metered |
| `true_loss_kwh` | F×H per component | kWh/h | `mv`, `dt_cu`, `dt_core`, `lv` from the power flow; `lv_dt` per DT |
| `loss_estimate_factor` | F×H | – | Multiplier on the utility loss estimate (background error × G × systematic) |
| `noise_mult` | F×H | – | Meter-error multiplier |
| `label_theft_consumer` | C×H | bool | B/D injection active |
| `label_unmetered_dt` | DT×H | bool | C injection active |
| `label_benign_change` | C×H | bool | Genuine consumption drop |
| `label_data_fault` | C×H | bool | E injection affects the reading |
| `events`, `benign_events`, `outages` | lists | – | Resolved ground truth |
| `ingestion` | dict | – | Records received, duplicates removed, never received, delayed |
| `data_hash` | str | – | SHA-256 fingerprint of all measurement arrays |

## Energy-balance payload (`GET /api/simulations/{id}/energy-balance`)

| Field | Unit | Meaning |
|---|---|---|
| `input_kwh` | kWh | Input-meter energy over the window (hours with a reading) |
| `metered_kwh` | kWh | Consumer readings received by the evaluation step |
| `imputed_kwh` | kWh | Expected-profile energy for missing or pending readings |
| `estimated_loss_kwh` | kWh | Calibrated technical-loss estimate |
| `unexplained_kwh` | kWh | input − metered − imputed − losses |
| `unexplained_pct_of_input` | % | 100 × unexplained / input |
| `sigma_kwh`, `z_score` | kWh, – | Propagated 1σ uncertainty and U/σ |
| `uncertainty_components_kwh` | kWh | Input meter, consumer meters, loss model, imputation |
| `data_quality` | – | Status, coverage, missing / pending readings, input gaps, outage hours |
| `hourly` | kWh/h | Per-hour terms (null where the input reading is missing) |

## Alert payload (`POST /api/simulations/{id}/detect`)

| Field | Meaning |
|---|---|
| `kind`, `id`, `feeder`, `dt` | What is flagged and where it sits in the network |
| `method`, `score`, `threshold`, `score_display` | Which detector, its raw score and decision threshold |
| `priority.level`, `priority.reasons` | P1/P2/P3/DQ and why |
| `text` | Generated explanation |
| `evidence` | Numbers behind the explanation |
| `features` | RF contributions or IF robust z per feature |
| `energy_at_stake_kwh_per_day` | Shortfall (consumer) or unexplained energy (boundary) |
| `truth` | Simulation ground truth; exists only because this is a simulation |

## Feature tables (experiments)

`artifacts/results/test_predictions_{consumer,dt,feeder}.csv.gz` hold `run`, `tau`, `unit`,
`label` and every method's score for every test window. All reported metrics are recomputable
from these files.
