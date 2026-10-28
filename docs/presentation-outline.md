# Presentation outline (E&L evaluation, about 12 minutes plus demo)

1. **Problem and SDG framing** (1 min)
   * Non-technical losses hurt utility finances and investment capacity: SDG 9 (resilient
     infrastructure, innovation), with links to SDG 7 (affordable, reliable energy).
   * The faculty's context: Sharavathi generation, the SRS Peenya receiving station, BESCOM's
     distribution network.

2. **What is real, what is modelled** (1.5 min)
   * Verified: SGS 1035 MW (KPCL); the Sharavathy pumped storage scheme is separate and proposed;
     SRS Peenya is a 220/66/11 kV KPTCL station; MESCOM serves Shivamogga, BESCOM serves
     Bengaluru Urban; BEE energy-accounting rules (2021).
   * Not verified: a dedicated Sharavathi → Peenya line. The model is meshed and illustrative.
   * Why theft analysis belongs at feeder and DT level: the twin's own power flow puts the
     modelled feeders at ~0.2 % of the 220 kV corridor flow.

3. **Research question** (0.5 min)
   * Does combining consumer-level anomaly detection with feeder/DT energy balance improve
     detection and prioritisation over threshold rules alone, on a held-out simulated benchmark?

4. **System** (2 min): architecture diagram (`docs/architecture/architecture.md`)
   * Synthetic data generator with named random streams and replay verification.
   * Vectorised radial power flow validated against pandapower; pandapower snapshot of the
     whole network.
   * Energy accounting: formula, calibrated loss estimate, imputation, propagated σ.
   * Detectors: rules, Isolation Forest, Random Forest (consumer-only vs combined).
   * Explanations: exact RF contributions, evidence-based narratives, P1/P2/P3/DQ priorities.

5. **Live demo** (3 min): follow `docs/demo-script.md`.

6. **Results** (2.5 min): from `docs/experiments/results.md`. Read the numbers from the file;
   do not round them up.
   * Consumer level: combined vs consumer-only vs rule (F1, PR-AUC, paired bootstrap ΔF1).
   * Benign confounders: genuine-drop false-flag rates.
   * Feeder / DT level and localisation top-1.
   * Robustness: noise, missing data, prevalence, loss-estimate error with and without
     calibration (the main failure mode and its mitigation).
   * Energy-balance validation: recovery of injected energy ≈ 1.00 including extra losses.

7. **Limitations and ethics** (1 min): `docs/limitations.md`
   * Synthetic labels; idealised injections; full AMI and DT metering assumed; calibration can
     absorb pre-existing theft; not a legal decision system.

8. **Contribution and future work** (0.5 min)
   * Contribution: an open, reproducible, explainable workflow and digital twin. The combination
     idea itself is established (Jokar et al., 2016).
   * Next: real or public datasets (e.g. SGCC) for the consumer layer, partial DT metering,
     reference-period selection for calibration, a temporal model against these baselines,
     cost-aware inspection scheduling.

## Viva preparation (likely questions)

* Why two power-flow solvers, and how do you know the sweep is right? (test tolerances)
* Why is the Random Forest score not a probability? Why use percentiles for Isolation Forest?
* What does z = U/σ assume? Why is σ conservative under normal operation?
* How does an unmetered load differ from under-recording in the evidence? (balance gap with and
  without matching consumer shortfalls)
* What leaks between train and test? (nothing at run level: grouped splits; the shared generator
  assumptions are a limitation)
* Why did Isolation Forest get worse with grid features?
* What breaks if technical losses are mis-estimated, and what does calibration cost?
