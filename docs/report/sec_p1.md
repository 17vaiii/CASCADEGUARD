<!-- OWNER: P1 | STATUS: ACTIVE -->
# P1 — Grid Simulation, AC Cascade Engine, and Contingency Search

**Owner:** Person 1 (Grid Simulation and Search Lead)  
**Status:** Implemented, verified with AC power flow convergence, and benchmarked.

---

## 1. Network Architecture & Corridor Modeling

The Sharavathi-to-Bengaluru 220 kV bulk power transmission corridor forms a critical 361 km backbone transferring hydroelectric energy from the Linganamakki reservoir to Bengaluru's Peenya distribution hub.

The network is modeled as a 39-bus, 76-line dual-circuit AC transmission corridor in pandapower:
- **Generation Hub (km 0):** Sharavathi hydro station acting as the grid slack bus ($V_m = 1.05$ p.u.).
- **Intermediate Substations:** Shimoga (km 110), Sira / KB Cross (km 215), and Nelamangala (km 320) providing bulk transformation and reactive shunt compensation.
- **Load Termination (km 361):** Peenya load center serving 180 MW peak demand.
- **Unfolded Dual Circuits:** Each 10 km section consists of two parallel circuits (Circuit A and Circuit B). When one circuit trips under contingency, its load transfers to the parallel circuit, providing realistic overcurrent cascades.

---

## 2. AC Cascading Failure Simulation Engine

The cascade engine implements physics-based iterative tripping:
1. **Initial Contingency (N-k):** Disconnects designated candidate lines ($t = 0$).
2. **Network Graph Analysis & Islanding:** Detects connected topological components via NetworkX. Any island severed from a slack generator is blacked out, and its loads are shed.
3. **AC Power Flow Re-solution:** Solves full non-linear AC Newton-Raphson equations with DC initialization for robust numerical convergence.
4. **Overcurrent Relay Tripping:** Identifies surviving branches with thermal loading exceeding $100\%$, disconnects them, and repeats the cycle until the network stabilizes or collapses.

---

## 3. Hydrological Constraints & Seasonal Demand

Operation is bounded by seasonal inflow and Linganamakki reservoir dynamics:
- **Monsoon:** Inflow 450 cumecs, reservoir at 85% capacity, hydro output up to 900 MW, reduced corridor demand (0.85x).
- **Post-Monsoon:** Controlled discharge, hydro output up to 600 MW, standard demand (0.95x).
- **Summer:** Depleted reservoir (35%), restricted hydro conservation (max 350 MW, 6,000 MWh/day), peak cooling demand (1.15x) creating maximum thermal line stress.

---

## 4. Search and Vulnerability Analysis

- **Seasonal Weak-Link Analysis:** Evaluated single-line outages across all 76 branches. Outages in Section 0 (Sharavathi exit) and Section 37 (Peenya entrance) produce the highest vulnerability.
- **Adversarial Attack Search:** Beam search discovered that simultaneous N-2 outages on parallel circuits of Section 0 completely sever generation, resulting in an immediate 360 MW blackout (180 MW at Bengaluru).
