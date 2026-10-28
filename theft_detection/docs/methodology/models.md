# Detection models, explanations and prioritisation

Code: `backend/gridwatch/features/build.py`, `detection/`, `explanations/explain.py`.

## 1. Unit of analysis

* **Consumer window**: one consumer × the 24 h ending at evaluation time τ.
* **Boundary window**: one DT or feeder × the 24 h ending at τ.
* Training and evaluation use τ = end of each simulated day (14 windows per run). The live
  dashboard evaluates every hourly step with the same functions.
* **Label**: 1 if a theft-like injection (B, C, D) is active for ≥ 12 of the 24 hours, 0 if
  for none, −1 (excluded) otherwise. Benign drops, data faults, noise and loss-estimate errors are
  negatives by definition.

## 2. Features (all causal: only data that had arrived by τ)

Consumer-only (14): observed/expected ratios over 24 h, 72 h and 7 days; peer-normalised
ratios (same feeder and category, removing weather and common-mode drift); 24 h z-score; share
of low and zero readings; peak-hour and off-peak ratios; a sudden-change ratio (72 h vs the
previous 7 days); completeness over 24 h and 7 days; shape correlation.

Grid context (8): DT and feeder unexplained energy as a ratio and z-score over 24 h and 7 days,
and the consumer's net shortfall relative to its DT's unexplained energy.

Boundary (15): balance ratio and z over 24 h, 72 h and 7 days; coverage; input gaps; imputed
share; share and minimum of consumers with a low peer ratio; consumer shortfalls relative to
the gap and to the input; consumer-rule hits (always computed with the *default* rule, so
user-tuned thresholds cannot shift a model input).

Expected profile: per consumer, mean of the 28-day history by (weekday / Saturday / Sunday) ×
hour, weekend profiles shrunk halfway toward the weekday shape; outage hours and late readings
excluded.

## 3. Methods

| Method | Level | Signals | Why it exists |
|---|---|---|---|
| Consumer threshold rule | consumer | consumer | Transparent baseline: flag if peer-adjusted 72 h consumption is ≥ 35 % below expected and ≥ 80 % of readings arrived |
| Feeder energy-balance rule | feeder (inherited by consumers) | feeder | Classical feeder audit: flag if unexplained ≥ 3 % of input **and** ≥ 2σ over 24 h. Both conditions, so neither large-but-uncertain nor tiny-but-significant gaps alone trigger it |
| Combined rule | consumer | consumer + DT | Consumer flag **AND** DT imbalance ≥ 2σ over 72 h (fuzzy AND = minimum of normalised scores) |
| Isolation Forest, consumer / consumer + grid | consumer | as named | Unsupervised: no labels needed. 200 trees, fitted on all training windows without labels |
| Random Forest, consumer / consumer + grid | consumer | as named | Supervised on synthetic labels: 150 trees, min leaf 3, √features, balanced subsampling |
| Boundary RF (balance + consumer aggregates) | DT, feeder | both | Supervised boundary classifier |
| Max-of-consumer scores | DT, feeder | consumer | Aggregates consumer-level methods to a boundary |

Rule thresholds are configurable (API `rules` object; `RuleConfig`). Each rule's score is
normalised so **1.0 = its configured threshold**.

**Isolation Forest specifics.** IF isolates outliers in *any* direction, but consumption far
*above* expectation is not a theft signal here. Features are therefore mapped one-sidedly
(shortfall = max(0, 1 − ratio), positive part of imbalance z, …) and completeness features are
left out. The anomaly score (−`score_samples`) is **not a probability**; the UI shows it as a
percentile of training scores ("higher than 99.2 % of training windows").

**Random Forest specifics.** `predict_proba` is reported as a *classifier score*. It is fitted
to synthetic labels and uncalibrated for real data, so it is not a probability of theft.

**Thresholds.** ML decision thresholds maximise F1 on validation runs (never test runs). Rules
use their configured thresholds; validation-tuned rule thresholds are reported separately as a
fairness check.

**Deep learning** was not added: the windows are short, tabular, engineered summaries; a
temporal model would need longer histories and a fairer baseline set to be justified.

## 4. Explanations

* **Rules**: each condition with observed value and threshold.
* **Random Forest**: exact additive per-feature contributions for the prediction (path
  decomposition, Saabas 2014): `score = base + Σ contributions` (tested to 1e-9).
* **Isolation Forest**: the most unusual one-sided features in robust z-units versus the
  training data. This is a descriptive heuristic, labelled as such, not an attribution.
* **Narrative**: sentences are generated from the evidence of that alert (observed vs expected
  kWh, peak/off-peak ratios, consecutive days below 75 %, DT/feeder unexplained energy and z,
  completeness, the largest DT imbalance inside a feeder, and the share of the gap explained by
  consumer shortfalls). Pattern sentences list the explanations compatible with the evidence,
  e.g. *"consistent with load that does not pass through any consumer meter, an error in the
  technical-loss estimate, or an input-meter error."* They never conclude that theft occurred.

## 5. Inspection priority (decision support)

| Level | Consumer alert | Boundary alert |
|---|---|---|
| **DQ** meter-data review | < 80 % of 72 h readings received | coverage < 90 % or > 10 % input gaps |
| **P1** field inspection, high | DT imbalance ≥ 2σ (72 h) and deviation ≥ 2 days | z ≥ 3 and significant ≥ 1 whole day |
| **P2** field inspection, medium | DT imbalance ≥ 1σ, or recent | z ≥ 2 |
| **P3** desk review | DT balance does not corroborate (possible genuine drop) | otherwise |

Ranking index = level weight × (1 + ln(1 + energy at stake per day)). Missing data is routed to
meter-data review, not to a field visit.

Anomaly detection (scores), risk ranking (priority) and legal determination are separate. The
software only does the first two, and only on synthetic data.
