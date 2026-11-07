<!-- OWNER: P5 | STATUS: ACTIVE -->
# Demo script (PRD §14 "Expected final demo") — about 6 minutes

Simulation-only research prototype; every recommendation is advisory.

**Setup (once):** `pip install -r requirements-p5.txt`, then run the P4 pipeline and the P5
experiment (see `docs/p5/p5.md` §6), then
`PYTHONPATH=src streamlit run src/cascadeguard/dashboard/app.py` and open http://localhost:8501.
**Recording:** `demo_media/demo_walkthrough.webm` (silent) and numbered screenshots show these steps.
**Fallback if anything is slow:** every number below is also in `data/models/*/…metrics.json`
and the **Results** tab, so the story can be told from the Results tab alone.

| # | Time | Do | Say / point at |
|---|---|---|---|
| 1 | 0:00 | Sidebar: role **Operator**, season **post_monsoon**. Grid Resilience tab. | 361 km corridor, both circuits per section coloured by loading; hydro 354 MW, no import. Assumptions banner. |
| 2 | 0:40 | Trip section **S0**, circuit **A** → **Simulate**. | No action: the parallel circuit overloads, the cascade blacks out the corridor (100 % lost). |
| 3 | 1:20 | Recommendation panel; **Apply plan** toggle. | One verified action: raise state-grid import at Nelamangala by about 44 MW, so Sharavathi hydro backs down. Loss 100 % → 0 %, verification **PASSED** (AC re-simulation). Similar past cases on the right. |
| 4 | 2:00 | Open **Incident brief**. | Cited, explanation-only brief; sources marked illustrative; operator approval required. |
| 5 | 2:30 | Season **summer**, tick **Lose state-grid tie**, circuits **none** → Simulate. | Losing 200 MW of import: automatic UFLS would shed 43 %. The plan ramps hydro by the full 80 MW allowed by ramp and reservoir limits and sheds a controlled 123 MW at Peenya: 30 %. |
| 6 | 3:20 | Season **monsoon**, S10 circuit A → Simulate; then enable **Theft-aware grid state** (intensity 3). | Metered view: N-1 is safe (99 % loading). With P4's estimated 12 MW of hidden load the same trip cascades, and the theft-aware plan is the one that holds on the real system (22 / 22 vs 0 / 22 in the study). |
| 7 | 4:20 | **Loss & Theft** tab (or role **Loss analyst**). | Technical vs non-technical split, feeder heatmap, ranked inspection list; open a lead to show reason codes and precedent. Leads, not verdicts. |
| 8 | 5:20 | **Results** tab. | Mitigation vs greedy and no-action per season, warm-start speed-up, theft-aware result, shared results table for both pillars. |
