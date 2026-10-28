# Faculty demonstration script (about 3 minutes)

**Before the session:** run `scripts\run.ps1`, open http://127.0.0.1:8000 in a browser at
1600 px or wider, and check that the top bar shows *Simulated data, illustrative network*.
Optional: open *Model evaluation* once so the results are cached.

Click **Start demo**. Each stage below is one click on the guide's button. The guide calls the
same API as the manual controls; nothing is pre-recorded.

| # | Time | On screen | What to say |
|---|---|---|---|
| 1 | 0:00 | Normal network, day 5 | "This is a simulated grid inspired by Sharavathi generation and the Peenya receiving station. Only the names are real; the network is illustrative and all data is synthetic. The moving dots follow an AC power flow solved by pandapower for this hour. We account for energy at each feeder head and each distribution-transformer meter against the smart meters behind them. Every feeder's unexplained energy is near zero." Point at the side panel: the four feeders draw about 0.2 % of the 220 kV line flow, which is why theft is analysed at feeder and DT level. |
| 2 | 0:30 | Scenario D injected on F2, orange ground-truth markers | "We now inject a simulated persistent anomaly: four consumers' recorded consumption falls by up to 65 % in their peak hours from day 6, while the energy they draw is unchanged. Same seed, so everything else is identical. The orange markers are ground truth that a utility would never have." |
| 3 | 0:50 | Timeline plays to day 10 | "Watch F2. Its feeder-head meter still measures the full energy, the consumer meters record less, so the unexplained energy climbs above the 3 % line. F2 and its DTs turn red because the detector's score crosses its threshold, not because we coloured them." |
| 4 | 1:30 | Detection run, alert list | "These are the actual outputs of the Random Forest on consumer and grid features and of the boundary model, ranked by inspection priority." Click an alert: it highlights on the diagram. |
| 5 | 1:50 | Investigation view | "The explanation is generated from this consumer's readings: recorded versus expected kWh, the peak-hour shortfall, and the DT's own energy balance. The bars show how each feature moved the score. Priority P1 needs both consumer-level and energy-balance evidence." |
| 6 | 2:20 | Method comparison | "Every method on the same data. The simple threshold rule also flags two consumers whose consumption genuinely dropped. The combined model does not, because their DTs show no unexplained energy. Across the 30-run test benchmark this pattern holds: see *Model evaluation*." |
| 7 | 2:45 | Reset, reproducibility check | "Reset to step 0 and regenerate from the seed: identical data fingerprint and identical scores. Any result here can be reproduced exactly." |

## If asked

* *"Is this real KPTCL data?"* No. See *Sources and limits*: what is publicly sourced, what is
  assumed and what is synthetic.
* *"Does red mean theft?"* No. Red means the score crossed a threshold, which is a reason to
  investigate. The explanation lists other possible causes, and data-quality problems are routed
  to meter-data review.
* *"How good is it?"* Open *Model evaluation*. Quote numbers with "on our synthetic benchmark".
* *"What happens with missing data?"* Inject Scenario E: coverage drops, imputation rises,
  σ widens, and the alerts are routed to *DQ* instead of field inspection.
* *"What if the technical-loss estimate is wrong?"* Inject Scenario G with −45 %: the feeder
  shows an apparent gap with no consumer-level shortfall, and the explanation names a loss-model
  error as one possibility. The results page also shows the calibration ablation.

## Fallback

If the browser misbehaves, the same steps work through the API docs at `/docs`:
`POST /api/simulations/demo`, then `POST /detect` with `t=228`, `GET /compare?t=228`,
`POST /replay?t=228`.
