<!-- OWNER: P4,P5 | STATUS: ACTIVE -->
# PRD checklist for P4 and P5

Last audited: 2026-11-07, after the fixes. Every row was checked against the PRD (`tmp/prd_extract.txt`, §6, §7, §9, §10, §14, §16).

**Legend:** ✅ built, results produced, checked working · ⏸️ left out on the project owner's instruction · 🔑 built, needs an API key to test live

**How it was checked**
- Root test suite: 87 of 87 passed (26 P1-P3, 29 P4, 32 P5).
- Both pipelines rerun with all fixes and logged to MLflow.
- Real browser (Playwright + Chromium) walked the whole demo: 0 console errors, 0 page errors. Evidence in `docs/p5/demo_media/`.
- Docker: dashboard and API images built from clean and run. Container API served `/health`, `/api/mitigate`, `/api/theft-score`.
- Real Qdrant 1.12.1: both case bases loaded, every search check found the right case.
- All results are from simulated data.

## P4: Theft and Loss Analytics

| Task | PRD item | Status | Result |
|---|---|---|---|
| P4-1 | Literature scan, dataset choice | ✅ / ⏸️ | Review and SGCC loader done. Running on public data left out by the owner. |
| P4-2 | T1 technical loss from power flow | ✅ | Estimated 2.68 % vs true 2.69 % of feeder input |
| P4-3 | T2 energy balance | ✅ | Feeder flags precision 1.00, recall 0.62; DT flags 0.90 / 0.83 |
| P4-4 | T3 anomaly models + gradient boosting | ✅ | Isolation Forest, autoencoder, peer deviation, GBM PR-AUC 0.71 |
| P4-5 | T4 calibrated fusion with confidence | ✅ | PR-AUC 0.72 vs 0.39 baseline, ECE 0.0055, conformal coverage 88.6 %, Venn-Abers probability interval on each lead. API accepts feeder and DT meter data. |
| P4-6 | Graph model over feeder topology | ✅ | GraphSAGE PR-AUC 0.67; did not beat fusion, so fusion ships |
| P4-7 | T5 reason codes | ✅ | On every lead, in API and dashboard |
| P4-8 | T6 inspection ranking | ✅ | 105,869 kWh in 40 visits vs 48,997 rule-based, 700 random |
| P4-9 | T7 tamper signals, look-alike negatives | ✅ | False flags at 0.5: vacancy 1.7 %, solar 0.57 %, new appliance 0 % |
| P4-10 | T9 theft-aware cascade experiment | ✅ | Simulator: monsoon SCADA view misses 31-81 of 196 cascades, theft-aware 0. Retrained GNN: monsoon x3 error 130 MW → 2.8 MW |
| P4-11 | Bias and false-positive analysis | ✅ | Overall FPR 0.10 %; commercial 0.36 % vs residential 0.03 %, reported |
| P4-12 | T8 HT tapping (stretch) | ✅ | 83 % recall for 15-30 MW at 0 % false alarms; 0 % below 5 MW |
| — | T10 similar theft cases | ✅ | API, dashboard, real Qdrant (3,696 cases) |
| — | §9 identifiers hashed in demos | ✅ | Dashboard hashes by default; API returns `consumer_ref` |
| — | §9 hundreds of thousands of consumers | ⏸️ | Left out by the owner. Largest run is 5,281. |
| — | §16.7 experiments in MLflow | ✅ | Run `cascadeguard-p4-theft`, status FINISHED |

## P5: Optimization, RAG, LLM and Dashboard

| Task | PRD item | Status | Result |
|---|---|---|---|
| P5-1 | Greedy and no-action baselines | ✅ | Evaluated on 471 events |
| P5-2 | R9, H2 OR-Tools model with hydro ramp | ✅ | Post-monsoon 100 % → 0.71 % lost; summer 42.9 % → 29.7 %; 0 hydro violations. Line switching is built and tested but never chosen on this radial corridor. |
| P5-3 | Closed-loop verification and fallback | ✅ | 74 of 74 verified, 0 fallbacks needed; unmitigable islanding flagged |
| P5-4 | R8 case retrieval, precision@k | ✅ | Precision@3 0.97 (GNN 0.98) vs 0.68 baseline; explanations stored; real Qdrant (74 cases) |
| P5-5 | Warm start, measured gain | ✅ | Direct 5.3x faster (4.9-7.9x across runs); seeded optimizer path also measured, 100 % pass |
| P5-6 | Dashboard, two views | ✅ | Real browser and container |
| P5-7 | Wire up views | ✅ | Cascade path, critical lines, confidence, similar cases, before/after, heatmap, inspection list |
| P5-8 | Corpus and cited LLM copilot | ✅ / 🔑 | Offline briefs and citation checks work. Corpus is project-written summaries. Live Claude call needs `ANTHROPIC_API_KEY`. |
| P5-9 | Demo script, recordings, fallback data | ✅ | Script, silent screen recording and screenshots in `docs/p5/demo_media/`; result tables committable as fallback data |
| P5-10 | Role-based views (stretch) | ✅ | Operator, planner, loss analyst |
| — | H3 reservoir limits | ✅ | Enforced via P1 `dispatch_hydro`, tested |
| — | P6 audit log | ✅ | `audit_id` on real API calls, with verification result |
| — | Docker images, compose entry | ✅ | Dashboard and API built and run; dashboard added to `docker-compose.yml` |
| — | §16.7 experiments in MLflow | ✅ | Run `cascadeguard-p5-mitigation`, status FINISHED |

## Still open

| Item | Why | Owner |
|---|---|---|
| Live Claude brief | Needs `ANTHROPIC_API_KEY` (no other key is needed) | You supply the key |
| Public dataset evaluation | Left out on your instruction | — |
| Hundreds-of-thousands scale run | Left out on your instruction | — |
| §16.7 peer code review | Needs a teammate | Team |
| P3 `/api/predict` and `/api/screen` | Still use P3's original checkpoint. The retrained one is in `data/models/root_gnn/`. | P3 |
| P1 `apply_season` `total_load_mw`; non-converged solve reports 0 MW | P4/P5 correct both in their own wrappers | P1 |

## Verify it yourself (PowerShell, repository root)

Docker is only needed for the last block.

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m pytest tests -q -W ignore                # expect 87 passed
.\.venv\Scripts\python.exe -m streamlit run src/cascadeguard/dashboard/app.py
```

| Step | Do in the dashboard | Expect |
|---|---|---|
| 1 | `post_monsoon`, S0, circuit A, Simulate | 100 % → 0 %, PASSED, raise import about 44 MW, cascade path table |
| 2 | `summer`, circuits `none`, tick Lose state-grid tie, Simulate | About 42 % → 29.7 %, hydro +80 MW, shed 123 MW |
| 3 | `monsoon`, S10, circuit A, Simulate | 0 %, no action needed |
| 4 | Turn on Theft-aware (intensity 3), Simulate | 100 % → 0 %, raise import about 18 MW, GNN probability 0.97 |
| 5 | `post_monsoon`, S0, A + B, Simulate | 100 % → 100 %, FAILED: no remedial action exists (correct) |
| 6 | Loss & Theft tab | Heatmap, loss split, 40 leads with hashed IDs; pick one for reasons |
| 7 | Results tab | Both pillars |

```powershell
# Optional: Docker Desktop must be running
docker compose --profile local-platform up --build -d qdrant mlflow api dashboard
.\.venv\Scripts\python.exe -m cascadeguard.retrieval.load_qdrant --url http://localhost:6333
# Dashboard http://localhost:8501  API http://localhost:8000/docs  MLflow http://localhost:5000
docker compose --profile local-platform down
```
