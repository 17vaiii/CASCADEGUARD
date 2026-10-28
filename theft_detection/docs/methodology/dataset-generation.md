# Synthetic dataset generation

Code: `backend/gridwatch/simulation/` (`generator.py`, `profiles.py`, `scenarios.py`,
`topology.py`, `feeder_flow.py`). Everything below is a **modelling assumption**; nothing is
fitted to Karnataka utility data.

## 1. Run structure

| Item | Value |
|---|---|
| Resolution | 1 hour. A reading is energy in kWh for the hour, numerically equal to average kW. |
| History (reference) period | 28 days (672 h). Used to learn expected profiles and to calibrate loss estimates. No scenario is injected here. |
| Observation period | 14 days (336 h) = the playback timeline. Step 0 = Monday 02 Mar, 00:00 on a synthetic calendar. |
| Default size | 4 feeders × 3 DTs × 25 consumers = 300 consumers, 302 400 consumer readings per run |
| Configurable | feeders 2–6, DTs per feeder 2–4, consumers per DT 5–80 |

## 2. Reproducibility

A run is fully defined by its `SimulationConfig` (JSON, validated by pydantic) including the
seed. Every random quantity comes from an **independent named stream**
`numpy.random.default_rng([seed, crc32(name), ...])` (`consumers`, `demand`, `benign`,
`outages`, `meters`, `comms`, `duplicates`, `injection/<n>`, `loss-model`). Consequences:

* the same configuration gives bit-identical data (`data_hash` = SHA-256 of all measurement
  arrays; the API's *replay* endpoint regenerates and compares it);
* a scenario run and the normal-operation run with the same seed share **identical background
  data**; only what the injection touches differs (verified by `tests/test_generator.py` and the
  *What changed vs normal?* button).

## 3. Consumers and demand

* **Categories** per DT drawn from feeder archetype mixes (industrial / mixed / residential
  feeders): residential, commercial, small industrial.
* **Daily energy**: lognormal, median 7 / 35 / 200 kWh per day for residential / commercial /
  industrial (order-of-magnitude assumptions for urban Indian LT consumers).
* **Hourly shape**: stylised templates (residential morning and evening peaks; commercial daytime
  plateau; single-shift industrial), shifted ±1 h and jittered per consumer; weekday / Saturday /
  Sunday multipliers.
* **Variation**: hourly lognormal noise (σ 0.28 / 0.16 / 0.13), AR(1) day-to-day factor, a
  shared AR(1) weather factor, and a mild seasonal drift (+0.15 % per day).
* **Power factor** (only for the power flow): 0.95 / 0.92 / 0.88.
* **DT sizing**: each DT takes the smallest standard rating (63–630 kVA) whose 70 % covers the
  99.5th-percentile apparent power of its consumers, with indicative no-load and copper losses.

## 4. Benign effects (present in every run, including Scenario A)

| Effect | Model | Label |
|---|---|---|
| Genuine consumption drop (vacancy, reduced operation) | share `benign_change_rate` (default 2 %) of consumers; 20–60 % of normal for 2–10 days | `label_benign_change` (negative for theft) |
| Supply outage | Poisson, `outage_rate` per feeder-week; 1–4 h; demand, meters and flows go to 0 | outage list |
| Communication delay | `base_delay_rate` (2 %) of readings arrive 2–24 h late | — |
| Lost readings | `base_missing_rate` (0.5 %) never arrive | — |
| Duplicate records | `duplicate_rate` (1 %) re-transmitted; removed at ingestion | ingestion stats |

## 5. Scenario injections

| Code | Injection | What changes | Theft-like label |
|---|---|---|---|
| A | none | — | — |
| B | `sudden_deviation` | Recorded (not drawn) energy of *n* consumers × (1 − m) from onset (step change) | yes, consumer |
| C | `unmetered_load` | Extra load at a DT's consumer bus, evening-weighted profile, peak = m % of the DT's average load. Flows through the power flow, the DT meter and the feeder-head meter, **no consumer meter** | yes, DT / feeder |
| D | `persistent_anomaly` | Recorded energy × (1 − m·ramp·w): ramps in over 72 h; w = 1 in the consumer's usual peak hours, 0.35 otherwise | yes, consumer |
| E | `missing_delayed` | Bursts (4–12 h) of lost readings or readings delayed 6–48 h, covering m % of the window, for *n* consumers | no (data fault) |
| F | `noise_stress` | Bias and random error of every meter on the feeder × m | no |
| G | `loss_estimate_error` | Utility loss estimate on the feeder × (1 + m/100) during the window | no |

Additionally `systematic_loss_error_pct` applies a persistent loss-model error to every feeder
over **history and observation** (e.g. wrong conductor data). Background loss-model error:
N(0, 5 %) per feeder.

**Why this differs from real theft labels.** The injections are idealised: they start and stop
at known times, have a known magnitude and ignore how real tampering behaves, how it is detected
or how often it occurs. Labels here are perfect; real labels come from inspections that are
sparse, delayed, biased toward already-suspected consumers and sometimes wrong. Results on this
benchmark therefore say how methods respond to *these* signal patterns, not how often they would
find theft in the field.

## 6. Physics: radial power flow

Each feeder is solved for every hour at once by a vectorised **backward/forward sweep**
(`feeder_flow.py`): constant-power loads at consumer-group buses, 11 kV line segments (ACSR
"Rabbit"-class R/X), DT series impedance from vk/vkr plus a constant-impedance no-load branch, and
one equivalent LV branch per DT. The 11 kV bus is held at 1.0 pu (OLTC assumption). Outputs:
feeder-head energy, DT secondary energy, and line, DT copper, DT core and LV losses.

Validation (`tests/test_feeder_flow.py`) against **pandapower** Newton-Raphson on the same
feeders: head P within 0.05 %, losses within 1 %, voltages within 5×10⁻⁴ pu. The remaining
voltage difference comes from transformer modelling (pandapower's T-model splits the series
impedance around the magnetising branch). Energy conservation (head = demand + losses) holds to
machine precision.

The displayed network snapshot is a separate **pandapower** AC power flow of the *whole* network
(meshed 220 kV, receiving station, 66 kV, all feeders) for the hourly-average demand of the
displayed step.

## 7. Meters and ingestion

| Meter | Bias (fixed per meter) | Random error | Missing |
|---|---|---|---|
| Feeder head (class 0.5S) | N(0, 0.3 %) | N(0, 0.2 %) | 0.1 % |
| DT (class 0.5S, LV CT) | N(0, 0.4 %) | N(0, 0.3 %) | 0.3 % |
| Consumer smart meter (class 1.0) | N(0, 0.25 %) | N(0, 0.4 %), 1 Wh resolution | via communication model |

Errors scale with `noise_level` (global) and Scenario F (per feeder). The utility does *not*
know these actual errors; its uncertainty model uses nominal figures.

Ingestion builds the record stream `(consumer, interval, value, arrival time)`, sorts by
arrival and keeps the first record per `(consumer, interval)`: duplicates are never
double-counted (`tests/test_energy_balance.py::test_duplicate_records_are_not_double_counted`).

## 8. Splits used in experiments

Benchmark runs are composite scenarios (`experiments/benchmark.py`): theft-like injections
reaching a target **prevalence** (1 % / 3 % / 8 % of consumers with recorded-consumption
anomalies, plus 0–2 unmetered loads), random benign stressors E/F/G, and randomised background
noise and missing rates. Train seeds 1000–1029, validation 2000–2009, test 3000–3029; sweeps use
4000+ and localisation 5000+. **Splits are grouped by run** so no run contributes windows to two
splits.
