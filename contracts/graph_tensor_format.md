<!-- OWNER: P3 | STATUS: ACTIVE -->
# Graph Tensor Format Contract (P3 / Cascade ML)

**Producer:** `cascadeguard.cascade_ml.graph_builder`  
**Consumers:** `cascadeguard.cascade_ml.gnn`, `cascadeguard.cascade_ml.screening`, `cascadeguard.api`  
**Target:** PyTorch Geometric `Data` graph representation of pre-contingency power grid states.

---

## 1. Node Tensors (`x`): `[num_buses, 4]`
Each electrical substation / bus is represented as a node:

| Channel | Feature | Unit / Scaling | Description |
|---|---|---|---|
| `0` | `vm_pu` | per-unit ($\approx 1.0$) | Pre-contingency bus voltage magnitude |
| `1` | `p_mw_norm` | $P / 100.0$ | Active power generation/load injection in 100 MW units |
| `2` | `q_mvar_norm` | $Q / 100.0$ | Reactive power generation/load injection in 100 MVAr units |
| `3` | `is_slack` | binary $\{0, 1\}$ | $1.0$ for Sharavathi slack / generator bus (km 0), $0.0$ for load buses |

---

## 2. Graph Connectivity (`edge_index`): `[2, 2 * num_lines]`
Bidirectional graph topology representing physical transmission lines:
- Forward edges: `(line_from_bus, line_to_bus)`
- Reverse edges: `(line_to_bus, line_from_bus)`

---

## 3. Edge Tensors (`edge_attr`): `[2 * num_lines, 4]`
Physical transmission line branch characteristics and contingency status:

| Channel | Feature | Unit / Scaling | Description |
|---|---|---|---|
| `0` | `r_ohm_norm` | $R / 10.0$ | Series resistance of the line |
| `1` | `x_ohm_norm` | $X / 50.0$ | Series reactance of the line |
| `2` | `loading_ratio` | $\text{loading\_pct} / 100.0$ | Pre-contingency line MVA loading ratio |
| `3` | `is_initial_trip` | binary $\{0, 1\}$ | $1.0$ if line is tripped at $t=0$ in the contingency, else $0.0$ |

---

## 4. Target Supervision Labels
For training and ground-truth evaluation:
- `y_lines`: `[num_lines]` binary vector indicating which lines tripped during the cascade ($1.0$ if in `failed_lines`).
- `y_cascade_size`: scalar count of total failed transmission lines.
- `y_load_loss`: scalar load shed in MW at the Bengaluru / Peenya endpoint.
- `y_has_cascade`: binary $\{0, 1\}$ indicator of whether initial trips caused secondary cascade propagation.

---

## 5. Model Output Contract (`contracts/CASCADE_PREDICTION.md`)
The model produces:
- `line_failure_probabilities`: Dictionary mapping line index or name to calibrated probability $\in [0, 1]$.
- `predicted_cascade_size`: Estimated count of tripped lines.
- `predicted_load_lost_mw`: Point estimate of unserved load in MW.
- `load_loss_conformal_interval`: $[L, U]$ 90% confidence bounds in MW.
- `graph_embedding`: 128-dimensional embedding for vector search.
