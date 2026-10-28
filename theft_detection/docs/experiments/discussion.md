# Discussion of the experimental results

Numbers come from [`results.md`](results.md) (generated from
`backend/artifacts/results/results.json`, run of 2026-10-22). Every statement is about the
**synthetic benchmark** described in `docs/methodology/dataset-generation.md`.

## 1. Answer to the research question

> *Does combining consumer-level anomaly detection with feeder/DT energy-balance analysis
> improve detection and prioritisation of simulated theft scenarios compared with
> threshold-based detection alone?*

**Yes for the supervised model, at both levels. Not automatically for every way of combining.**

* **Consumer level.** The Random Forest on consumer + grid features (F1 0.679, PR-AUC 0.686)
  beats the same model on consumer features only (F1 0.552, PR-AUC 0.614): paired
  ΔF1 = +0.127 [0.079, 0.169] and ΔPR-AUC = +0.072 [0.030, 0.110]. Against the consumer
  threshold rule (F1 0.462) the gain is ΔF1 = +0.217 [0.177, 0.258].
* **Boundary level.** The boundary Random Forest using energy-balance features *and* consumer
  aggregates reaches F1 0.867 at feeder level and 0.785 at DT level, against 0.740 / 0.650 for
  the best consumer-only aggregate: paired ΔF1 = +0.127 (feeder) and +0.135 (DT), both with
  CIs above 0.
* **Prioritisation.** The combined model's false flags are not dominated by genuine
  consumption drops (it flags 22 % of benign-drop windows versus 55 % for the consumer-only RF
  and 68 % for the rule). In the priority scheme, an alert needs balance corroboration to become
  P1, which pushes uncorroborated drops down to P3 desk review.

## 2. Why combining helps, and when it does not

**Mechanism.** A drop in recorded consumption is ambiguous on its own: the consumer may have
used less (vacancy, closure) or the meter may have recorded less than was drawn. The DT/feeder
balance separates the two: under-recording leaves energy that entered the boundary unaccounted
for, a genuine drop does not. The consumer's 24 h ratio and z-score are still the most important
features (impurity importance 0.17 and 0.15); the much lower benign-drop flag rate of the
combined model is the evidence that the grid features act as a veto on uncorroborated drops. The disagreement panel in the dashboard shows this case by case.

**The naive combination is not free.** The combined *rule* (consumer flag AND DT imbalance
≥ 2σ) raises precision from 0.43 to 0.68 but loses recall (0.50 → 0.32), because small or
recent under-recording does not yet move a DT balance by 2σ. Its F1 change is −0.031
[−0.081, 0.014], indistinguishable from zero, although its ranking quality improves
(ΔPR-AUC = +0.080). A hard AND gate is too strict; a learned combination weighs the evidence.

**Unsupervised combination hurt.** Isolation Forest with grid features is *worse* than without
(ΔF1 = −0.152). A plausible explanation (not tested separately): IF has no notion of which
features matter, and grid features are identical for every consumer behind a DT, so many
isolation paths separate whole DTs instead of individual consumers, diluting the consumer-level
signal. Without labels, combining signals needs domain structure
(like the rule's AND gate), not just more columns.

**Feeder rule threshold.** The default energy-balance rule (unexplained ≥ 3 % and ≥ 2σ) is very
precise (0.99) but misses most events (recall 0.35): a few under-recording residential
consumers change a feeder's balance by well under 3 %. Tuned on validation, the same rule
reaches F1 0.838, close to the boundary Random Forest's 0.867. So at feeder level **most of the
gain over "the threshold rule" is threshold choice**, and the honest comparison is 0.867 vs
0.838. The 3 % default was kept in the dashboard because it is transparent and conservative,
not because it is optimal.

## 3. Robustness

| Stress | What happened | Interpretation |
|---|---|---|
| Lower prevalence (1 % of consumers) | Combined RF stays at F1 0.668; consumer-only RF falls to 0.306 and the rule to 0.331 | With few positives, the benign drops dominate the consumer-only false positives; balance corroboration filters them |
| Meter noise ×4 | Consumer models barely change; boundary RF false-positive rate rises 0.03 → 0.12 | σ uses *nominal* meter accuracy; unknown extra noise inflates z |
| Missing readings 20 % | Combined RF F1 0.738 → 0.628; boundary RF FPR 0.03 → 0.29 | Heavy imputation makes balances uncertain; the DQ priority level routes such alerts to meter-data review, but the boundary classifier itself does not know to abstain. **A real weakness.** |
| Persistent loss under-estimate −20/−40 %, calibration **off** | Boundary RF FPR 0.99 / 1.00 | An uncorrected loss model turns into apparent theft on every feeder |
| Same, calibration **on** (default) | No change at any level | Reference-period calibration absorbs persistent bias, but would also absorb theft already present in the reference period (see limitations) |

## 4. Localisation and timing

* With theft on one feeder, the highest-scoring feeder is the right one in 94.9 % of windows
  (boundary RF) and 94.2 % (balance rule), versus 78.3 % for the best consumer-only aggregate.
  At DT level both balance-based methods reach 95.7 %. **Localising a gap is what energy
  balances are good at.** Pointing to the individual meter needs consumer-level evidence.
* Unmetered loads (no consumer-meter signature) are caught by balance-based methods in every
  test event, with a median delay of 1–2.5 h; consumer-only aggregates catch 60–80 % of them,
  after ~48 h and only incidentally (through other anomalies inside the same DT in these
  composite runs).
* Recorded-consumption anomalies take a median of 45 h (combined RF) to 69 h (rule) to be
  flagged at consumer level, because the persistent anomaly ramps in over 72 h and the features
  use 24–72 h windows. This is a property of the injected shape as much as of the detectors.

## 5. Energy-accounting validity

The balance is not just a feature generator. Its accounting is checked against the physics:
the feeder-level unexplained energy recovers 0.9986 ± 0.0026 of (injected unmetered energy +
the extra technical losses it causes), and the DT boundary recovers the injected energy plus LV
losses within 3 % (unit test). The ≈ 7 % excess at feeder level (ratio 1.074 vs injected energy
alone) is the physically expected extra I²R loss, which the utility's loss estimate cannot see.

## 6. Threats to validity

* **Same generator for train and test.** Different runs and seeds, but the same assumptions.
  The supervised models' advantage partly reflects that the test distribution matches training.
  Real deployment needs retraining and evaluation on inspected real cases.
* **Idealised injections and perfect labels.** See `docs/limitations.md`.
* **Threshold selection on validation** gives ML methods tuned operating points while rules
  keep transparent defaults. The tuned-rule table (results §4) is the fairness check, and
  threshold-free PR-AUC tells the same story at consumer level.
* **Demo seed** was selected for clarity and is not part of any reported number.
* **Runtime** was measured on one laptop while other processes ran. Feature computation grows
  faster than linearly at the largest size (627 ms/step for 1,920 consumers), which would need
  optimisation (incremental windows) for city-scale use.

## 7. What this means for the project's contribution

The results support the project's thesis on its own benchmark: **energy accounting and
consumer analytics are complementary**. The balance says *where* energy goes missing and guards
against benign drops; consumer analytics say *which meter* to examine. The value is in the
combination, the uncertainty-aware accounting and the explanation, not in a novel algorithm,
since the combined-signal idea is established in the literature (Jokar et al., 2016).
