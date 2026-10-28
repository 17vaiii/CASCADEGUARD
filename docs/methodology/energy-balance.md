# Energy-balance methodology

Code: `backend/gridwatch/energy_balance/` (`balance.py`, `loss_model.py`).

## 1. Monitoring boundaries

| Boundary | Input meter | Output meters | Technical losses inside |
|---|---|---|---|
| **Feeder** | Feeder-head meter on the 11 kV bay of the distribution substation | All consumer smart meters on the feeder | 11 kV line, DT copper and no-load, LV network |
| **DT** | DT meter on the 433 V side of the transformer | Consumer smart meters behind that DT | LV network only |

Transmission-level flows are **not** used for accounting: they are dominated by dispatch and
interconnection (see `docs/research/source-note.md` §1.6).

## 2. Formula

For boundary *B*, hourly intervals *h* in a window *W*, evaluated at time τ (only data that
had arrived by τ is used):

```
U = E_in − E_metered − E_imputed − L_est            [kWh]

E_in       = Σ_h input-meter reading                          (hours with a reading only)
E_metered  = Σ_h Σ_i reading_i,h   for readings received by τ
E_imputed  = Σ_h Σ_i expected_i,h  for readings missing or still in transit at τ
             (0 during a known outage, i.e. when the feeder-head meter reads 0)
L_est      = k_B × Σ_h L_raw,h      (utility-side estimate, §3)
```

* All terms are **energy in kWh** over identical hourly intervals. Instantaneous power (MW) is
  shown only on the network canvas from the power-flow snapshot and never mixed into the
  balance.
* **Incompatible time windows** cannot occur: hours with a missing input-meter reading are
  dropped from *both* sides, and hours after τ are excluded.
* **Unexplained energy as % of input** = 100 U / E_in.

## 3. Technical-loss estimate

`loss_model.py` implements a **one-pass analytic estimate** that a utility could compute from
network records and the energy it sees. This is deliberately not the simulator's iterative
power flow:

* per DT: P = metered + imputed energy, Q = P·tan φ, where tan φ is the energy-weighted value of
  tariff-category power factors;
* one-pass voltage drop ΔV ≈ R·P + X·Q (per unit) down the feeder;
* series losses R(P² + Q²)/V² for the LV branch, DT copper and each 11 kV segment, plus rated DT
  no-load loss while energised.

It cannot see energy that bypasses consumer meters, so an unmetered load also adds unestimated
**extra losses** to U. The feeder-level recovery ratio is therefore > 1, and ≈ 1.00 once those
extra losses are included (`docs/experiments/results.md` §9).

**Calibration** (default on). Per-boundary factor fitted on the 28-day reference period:
`k_B = Σ(E_in − E_metered − E_imputed) / Σ L_raw`, clipped to [0.5, 2]. It removes persistent
loss-model bias (wrong conductor data, power-factor assumptions). **Limitation:** any
non-technical loss already present during the reference period would be absorbed into k_B and
become invisible to the balance. The synthetic history is clean by construction, which flatters
calibration; in practice the reference period has to be chosen carefully (for example right
after an inspection campaign), and consumer-level change detection still matters.

## 4. Uncertainty (1σ)

Using **nominal** accuracy figures, because the utility does not know the true meter errors:

```
σ² = (b_in·E_in)² + r_in²·Σ_h e_in,h²                    input meter: bias + random
   + Σ_i [(b_c·E_i)² + r_c²·Σ_h e_i,h²]                  consumer meters, independent
   + (0.15·L_est)²                                       loss estimate
   + Σ_i [Σ_h sd_i,h² + (0.2·E_imputed,i)²]              imputation
z  = U / σ
```

with b/r = 0.3 %/0.2 % (feeder head), 0.4 %/0.3 % (DT), 0.25 %/0.4 % (consumer). Under normal
operation the daily z-scores have SD ≈ 0.3 with calibration (≈ 0.6 without), so the model is
conservative (`tests/test_energy_balance.py::test_normal_operation_is_within_uncertainty`).

## 5. Data-quality handling

| Problem | Handling | Shown as |
|---|---|---|
| Missing consumer reading | Imputed from the expected profile, with added variance | `imputed_kwh`, coverage |
| Delayed reading | Imputed until it arrives, then used | "pending (delayed)" count |
| Duplicate records | First record per (consumer, interval) kept at ingestion | duplicates removed |
| Measurement noise | Propagated into σ | uncertainty budget |
| Incomplete coverage | Coverage = received / expected readings | quality status |
| Outage | Feeder meter reads 0 → hour contributes 0 to both sides | outage hours |
| Missing input reading | Hour dropped from both sides | input-meter gaps |
| Loss-estimate uncertainty | 15 % σ term; calibration | loss-model σ |

Quality status: **good** if coverage ≥ 98 % and no input gaps; **fair** if ≥ 90 % and ≤ 2 gaps;
otherwise **poor**.

> **Unexplained energy imbalance is an investigation signal, not proof of electricity theft.**

## 6. Verification

`tests/test_energy_balance.py`:

* the identity U = E_in − M − I − L holds exactly, and hourly terms add up to the window total;
* normal operation stays within the propagated uncertainty;
* **known case:** an injected unmetered load is recovered at the DT boundary within 3 % of
  (injected energy + the extra LV losses it causes, taken from the physics);
* feeder-head energy = demand + true losses (conservation);
* missing data raises imputation and σ, not the unexplained energy;
* delayed readings move from "pending" to "metered" when they arrive;
* duplicates are not double-counted; outage hours are zero on both sides; input gaps drop hours;
* calibration removes a persistent −35 % loss-model bias.
