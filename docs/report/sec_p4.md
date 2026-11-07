<!-- OWNER: P4 | STATUS: ACTIVE -->
# P4 — Theft and Loss Analytics

**Owner:** Person 4 (Theft and Loss Analytics Lead)
**Status:** Implemented, tested and evaluated on simulated data (updated 2026-11-07).
**Code:** `src/cascadeguard/theft/` · **Config:** `configs/theft/models.yaml` · **Details:** `docs/p4/p4.md`

> All results come from simulation. Scores are leads for field inspection, never evidence of
> theft, and every lead requires human verification before any action.

---

## 1. Problem and approach

Distribution losses mix two different things. **Technical loss** is physics: I²R heating in
lines and transformer iron and copper losses. **Non-technical loss (NTL)** is behaviour: meter
bypass, stopped meters, tampering, hooking and direct tapping. Treating the total as one number
hides where energy is actually being lost. Real theft labels are also scarce and biased towards
what inspectors already look for. The design therefore depends on physics and injected ground
truth rather than on real labels (PRD §7.1):

1. **Physics first.** A power-flow model gives the expected technical loss of every feeder.
   Whatever remains unexplained at a feeder or distribution transformer (DT) is candidate NTL.
2. **Behaviour second.** Consumer models look for patterns that break from the consumer's own
   history and from comparable peers.
3. **Fusion.** A high feeder or DT residual raises the prior for every consumer below it. A
   consumer with a strong anomaly on a high-residual DT gets the highest score.

## 2. Simulated distribution layer

The corridor model (P1) ends at substations, so P4 adds a distribution layer below them: 48 feeders
at 11 kV, 264 DTs (62 % with an energy meter) and 5,281 residential, commercial and small-industrial
consumers, metered hourly for 90 days. The first 45 days are a reference period and the last 45 a
scoring window. Five theft types are injected with known labels (meter bypass, meter stop, night
tapping, hooking, temporary tampering; 5 % of consumers, clustered on hotspot feeders).

To avoid the PRD risk of synthetic theft being "too easy to detect", the data deliberately
includes hard negatives:
- legitimate look-alikes on 10 % of consumers (rooftop solar, new appliances, vacancy);
- public holidays;
- meter communication gaps;
- legitimate unbilled loads (streetlights, late-billed new connections);
- input-meter bias, drift and noise;
- spurious tamper alarms, including reverse-current events caused by solar export.

## 3. Technical loss and energy balance (T1, T2)

Each feeder is a pandapower radial model with trunk segments, 11/0.433 kV transformers and an
aggregated LV network. A loss curve `loss = a + bP + cP²` is fitted from power-flow runs at ten
loading levels (maximum fit error 0.2 %) and evaluated on every measured interval. For the
transmission corridor, section losses come directly from the P1 model: 13.0 MW, or 3.5 % of
generation.

Estimated distribution technical loss was 2.68 % of feeder input, against a true 2.69 %. Even
without theft, every feeder carries 1.5–2 % of unexplained loss from streetlights and meter error.
P4 therefore uses the **change** of each node's residual against its own reference period,
expressed as a z-score. At z ≥ 3, the 26 flagged feeders all contained theft (precision 1.00,
recall 0.62), and DT flags reached precision 0.90 at recall 0.83. Estimated NTL per corridor
substation matches the truth closely: PEENYA 1.65 % against 1.63 %, SHIMOGA 1.24 % against 1.26 %.

## 4. Consumer-level detection (T3, T4, T7, P4-6)

Seventeen interpretable behaviour features feed the consumer models. They compare the scoring
window against the reference period and against same-feeder, same-type peers: lowest 7-day ratio,
step drop, zero-read runs, night-share shift, a daytime "solar signature", profile correlation
and peer z-scores. Tamper-log counts and the DT and feeder residual context are added.

On the held-out test split (792 consumers, 40 thefts, K = 40), the fusion model outperformed
every single-signal baseline:

| Model | AUROC | PR-AUC | Precision@K |
|---|---|---|---|
| Threshold rule (consumption drop) | 0.79 | 0.39 | 0.33 |
| Isolation Forest / autoencoder / peer deviation | 0.72 / 0.74 / 0.78 | 0.29 / 0.41 / 0.37 | 0.23 / 0.43 / 0.38 |
| Gradient boosting | 0.92 | 0.71 | 0.65 |
| GraphSAGE over the feeder → DT → consumer graph | 0.90 | 0.67 | 0.63 |
| **Fusion (stacked, calibrated)** | **0.92** | **0.72** | **0.65** |

Random inspection would reach a precision of 0.05. Meter bypass, meter stop and temporary
tampering were all found within the top K (recall 1.00 each). Hooking and night tapping reached
only 0.12, which is physically expected: those thefts leave the consumer's meter unchanged, so only
the network energy balance can reveal them. The graph model did not improve on fusion, so fusion is
the shipped model; this negative result is reported.

**Calibration.** An inspector should only be told "70 % likely" if that is true. Temperature
scaling reduced expected calibration error from 0.012 to 0.0055. Split-conformal prediction sets
at 90 % reached 88.6 % test coverage. Each lead is labelled high, medium or low confidence and carries
a Venn-Abers probability interval (mean width 0.11 on the top 40 leads).

## 5. Explanations, inspection planning and precedent (T5, T6, T10)

Every lead carries reason codes. Supporting codes include "consumption fell 59 % below its own
history", "peers on the same feeder changed by +9 % while this consumer changed by −30 %",
"transformer residual rose by 27 % of its input" and tamper events. Mitigating codes include a
rooftop-solar pattern, missing reads or a balanced network. All wording says "suspected" and ends
with a request for field verification.

Inspection planning ranks consumer leads and **network leads** together. A network lead is a DT
whose residual is not explained by the consumer leads below it, and the crew is told to patrol for
hooks or direct taps. With 40 visits:

| Strategy | Precision | Recovered energy (kWh) | kWh per visit |
|---|---|---|---|
| Random | 0.04 | 700 | 18 |
| Rule-based (largest drop) | 1.00 | 48,997 | 1,225 |
| Score only | 1.00 | 24,284 | 607 |
| **Expected recovered energy (+ crew routes)** | 0.88 | **105,869** | **2,647** |

Ranking by expected recovered energy recovered 2.2 times the rule-based energy. A few hits are
traded for 13 network leads that uncover high-volume unmetered theft. Greedy crew routing from each
substation depot adds a small travel saving.

For each lead, the five most similar past cases (cosine similarity over the standardised evidence
vector) are shown as precedent. For test-set thefts, 48 % of retrieved cases were confirmed thefts.
The case vectors are padded to the 128-dimensional P2 Qdrant `theft_cases` collection.

## 6. Ethics and fairness (P4-11)

Scores are leads, not accusations. The false-positive rate is kept visible, and the system is
optimised for precision at the inspection capacity because wrongful flags harm consumers. At a
probability threshold of 0.5 the overall false-positive rate was 0.10 %. However, false flags fell
unevenly: commercial consumers had an FPR of 0.36 % and small-industrial consumers 0.28 %, against
0.03 % for residential consumers, and rural FPR (0.16 %) was higher than peri-urban (0.05 %). These
disparities are reported rather than tuned away. They argue for human review, and for extra peer
groups for commercial load shapes before any real deployment. IDs are synthetic pseudonyms, and the
API audit log stores consumer IDs and a payload fingerprint, never raw meter reads.

## 7. The link between the pillars: theft-aware cascade risk (T9)

Hidden theft load makes real line loading higher than SCADA shows. P4 converts its estimated NTL
into a hidden-load vector per corridor substation, then runs the P1 AC cascade simulator on three
states of the same season. The first state holds metered demand only (the SCADA view), the second
adds P4's estimated hidden load, and the third adds the true hidden load as ground truth. Each
state is tested against 196 N-1 and N-2 contingencies.

In monsoon, single-circuit outages leave the parallel circuit at about 99 % of its rating. **Just
4 MW of hidden load turned 31 of 196 apparently safe contingencies into real cascades, and the
SCADA-only view missed all 31.** At three to five times the simulated NTL level it missed 81. The
theft-aware state missed none, and load-loss error fell from 49–135 MW to under 0.1 MW. In
post-monsoon at five times the NTL level, SCADA missed 70 cascades and the theft-aware state none.
This is the product's core novelty: **theft detection directly improves grid-security
assessment.**

A GNN trained on the corridor model with varied hidden load (test AUROC 0.9996, load-loss MAE 6.0 MW
against 108 MW for a Random Forest) also recovers much of this as a fast surrogate: in monsoon at three
times the NTL level its load-loss error falls from 130 MW on the metered state to 2.8 MW on the
theft-aware state. Where hidden load does not decide the outcome (summer), its error does not improve.

## 8. HT line tapping on the corridor (T8, stretch)

On the 220 kV corridor, SCADA measurements exist only at four of the five substations. A
generalised-likelihood-ratio test checks whether a load at one of the 34 tap buses explains the
measurement residuals. At a 0 % false-alarm rate it detected 83 % of 15–30 MW taps and 39 % of
5–15 MW taps, with a median location error of 20 km. The unknown load at the unmetered Sira
junction (±10 %) looks like a 4 MW tap and sets the detection floor.

## 9. Limitations

- All data is simulated, and every electrical and behavioural parameter is an assumption.
- No real BESCOM or KPTCL data was used. The SGCC public theft benchmark is supported by a loader
  but has not been evaluated.
- Theft that leaves meters unchanged (hooking, tapping) can be localised only to a DT, not to a
  consumer.
- T9 assumes the estimated NTL ratio per substation also holds at the corridor scale.
