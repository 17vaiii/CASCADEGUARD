<!-- OWNER: P1 | STATUS: ACTIVE -->
# P1 Release 1 Handoff: Grid Corridor Model & AC Cascade Engine

**Producer:** Person 1 (Grid Simulation and Search Lead)  
**Consumers:** Person 2 (Data Platform), Person 3 (Cascade ML), Person 4 (Theft Analytics)  
**Status:** Completed and Verified.

---

## 1. Delivered Artifacts

1. **Sharavathi 220 kV Corridor Model (`src/cascadeguard/grid/corridor_model.py`)**:
   - 39 buses (5 primary substations: Sharavathi, Shimoga, Sira, Nelamangala, Peenya; 34 virtual tap buses at 10 km intervals).
   - 76 transmission lines (unfolded dual-circuits per section: Circuit A and Circuit B).
   - AC power flow converged with Newton-Raphson (`init='dc'`).
2. **Seasonal Dispatch & Hydro Constraints (`src/cascadeguard/grid/seasons.py`, `hydro.py`)**:
   - Seasonal operating profiles: `monsoon` (0.85x load, 900 MW hydro), `post_monsoon` (0.95x load, 600 MW hydro), `summer` (1.15x load, 350 MW hydro).
   - Linganamakki reservoir parameters: dead storage, turbine efficiency, ramp limits, and daily energy limits.
3. **Iterative AC Cascade Engine (`src/cascadeguard/sim/cascade_engine.py`)**:
   - Outage trip injection, island detection via NetworkX connected components, generation-less island load shedding, AC re-solve, and iterative overcurrent relay tripping.
   - Verified N-1 single circuit outage cascade propagation and N-2 simultaneous circuit trip resulting in full corridor load loss.
4. **Vulnerability Search (`src/cascadeguard/sim/weak_link.py`, `attack_finder.py`)**:
   - Seasonal weak-link ranking and beam-search adversarial attack discovery.

---

## 2. Interface Contracts for Downstream Roles

- **For P2 (Data & Platform):** Expose `simulate_cascade` and `build_corridor_network` for Parquet scenario generation batches.
- **For P3 (Cascade ML):** Output snapshot records with pre-contingency bus voltages, branch loadings, initial trips, and post-cascade failed lines and load losses.
- **For P4 (Theft Analytics):** Model electrical physical line parameters ($R, X$) for $I^2 R$ technical loss estimation.
