# Acceptance-test record

Executed on 2026-10-22 (Windows 11, Python 3.12.10, Node 24.15, Chromium 131 via Playwright
1.49.1). "Passed" means an automated test executed and passed, not that code exists.

| # | Acceptance test (project brief §18) | How it was verified | Result |
|---|---|---|---|
| 1 | Initial state shows the labelled simulated network and its baseline | UI test 1: feeder tags, buses, "Simulated data" badge, converged AC power flow, feeder overview. API test `test_initial_state_has_network_and_power_flow` | **Passed** |
| 2 | Play, pause, reset, move through steps | UI test 2: step forward/back, play advances, pause holds, reset returns to 0. API test `test_timeline_bounds` | **Passed** |
| 3 | Select a feeder and view its measurements | UI test 3: side panel shows the feeder balance; the feeder is marked selected, other feeders dimmed | **Passed** |
| 4 | Displayed energy balance matches the backend calculation | UI test 4: the formula value on screen equals `GET /energy-balance` for the same boundary and window. API test `test_energy_balance_matches_state`; identity, known-case and conservation tests in `test_energy_balance.py` | **Passed** |
| 5 | Introduce a simulated anomaly and observe the data changes | UI test 5: inject Scenario C, "What changed vs normal?" lists changed DT and feeder meters. API test `test_scenario_injection_changes_data` (exactly the targeted consumer meters change); `test_generator.py` isolation tests | **Passed** |
| 6 | Detection executes and returns actual outputs | UI test 6-7: "Run detection" returns alerts with timing. API test `test_detection_and_explanations` (persists a detection record) | **Passed** |
| 7 | Alert reason grounded in measured features and computed outputs | UI test 6-7: explanation contains the computed unexplained kWh, % of input and σ. `test_rf_contributions_are_exact` (contributions add up to the score within 1e-9) | **Passed** |
| 8 | Selecting the alert highlights the correct element | UI test 8: clicking a DT alert marks that DT selected, with status "alert", and dims other feeders | **Passed** |
| 9 | Methods compared using actual evaluation results | UI test 9: the evaluation view shows the F1 read from `results.json`; the step-level comparison table renders. Experiments: `python -m gridwatch.experiments.run` (1,187 s) | **Passed** |
| 10 | Same configuration and seed reproduce data and results | UI test 10 ("identical data"); API test `test_replay_is_reproducible` (score difference ≤ 1e-12); `test_same_seed_same_data`. Independently trained model bundles have identical thresholds (max difference 0.0) | **Passed** |
| 11 | Reset returns the scenario to its baseline state | UI test 11: "Normal operation" creates scenario A with no events and the status reads "no event injected"; timeline reset tested in UI test 2 | **Passed** |
| 12 | Dashboard and report separate verified facts, assumptions, synthetic data and results | UI test 12 (Sources and limits headings); `docs/research/source-note.md`; generated `docs/experiments/results.md` | **Passed** |
| 13 | A new user can follow the README and run the app | The repository was copied without any generated artefacts (no venv, node_modules, build output or models) and the documented steps were run: `scripts\setup.ps1`, then `scripts\run.ps1`. The app trained its models on first start (~30 s), became healthy in 56 s, and **all 12 UI tests passed against this clean install** | **Passed, with a caveat** (below) |
| — | Guided demo runs end to end | UI test "demo": all seven stages, ending with the reproducibility check | **Passed** |

Totals: **43/43 backend tests** (`pytest`, ~17 s) and **12/12 UI tests**, run three times:
against the dev server, the production build, and the clean install.

## Problems the tests found, and the fixes

* **Power-flow convergence after an outage.** After a feeder outage, every later pandapower
  solve failed: the solver warm-started from NaN voltages on isolated buses. The canvas would have
  lost its flows midway through the demo. Fixed: warm start only after a converged solve with the
  same topology, otherwise a flat start. Regression test
  `test_snapshot_survives_outage_and_restoration`.
* **Setup script reported success after a failure.** PowerShell 5.1 does not stop on failing
  native commands, so `setup.ps1` printed "Setup complete" after `npm ci` failed. Fixed: each
  step checks its exit code.
* **Windows path length.** The first clean-install attempt ran in a very deep temporary folder
  and `npm ci` failed because an install script's path exceeded Windows' 260-character limit.
  Re-running from a short path (a `subst` drive) succeeded. **Caveat:** keep the project in a
  reasonably short path, or enable Windows long-path support. The project's real location
  (~140 characters to `node_modules`) works.
* **Electrical coupling in tests.** Two tests first assumed that an unmetered load changes
  nothing outside its own DT; the physics correctly shows a small voltage-coupling effect on
  same-feeder DTs. The tests now bound that effect (< 1 % / < 0.1 %).

## Not verified

* **Docker** (`Dockerfile`, `docker-compose.yml`): Docker was not installed, so the files were
  never built or run.
* **Linux/macOS scripts** (`scripts/*.sh`): written but not executed.
* Browsers other than Chromium, and screens narrower than ~1366 px (the layout targets a
  laptop or projector at ≥ 1440 px).
