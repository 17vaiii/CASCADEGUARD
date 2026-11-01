<!-- OWNER: P3 | STATUS: ACTIVE -->
# P3 — Cascade Machine Learning, Calibration, and Screening

**Owner:** Person 3 (Cascade ML Lead)  
**Status:** Implemented, trained, calibrated, and smoke-verified.

---

## 1. Overview & GNN Architecture

Transmission line cascading failures in the Sharavathi–Bengaluru corridor were modeled using a multi-task Graph Neural Network (**CascadeGNN**) running on PyTorch Geometric.

The grid is formulated as a directed bidirectional multigraph $\mathcal{G} = (\mathcal{V}, \mathcal{E})$:
- **Node features** $\mathbf{x}_v \in \mathbb{R}^4$: Pre-contingency voltage magnitude ($V_m$ in p.u.), normalized active power injection ($P/100$ MW), reactive power injection ($Q/100$ MVAr), and slack bus indicator.
- **Edge features** $\mathbf{e}_{uv} \in \mathbb{R}^4$: Series resistance ($R/10$ $\Omega$), reactance ($X/50$ $\Omega$), pre-contingency loading ratio ($\text{loading}/100$), and initial contingency status ($1.0$ if tripped at $t=0$, else $0.0$).
- **Message-Passing Engine**: Multi-layer edge-conditioned message passing (`GridEdgeConv`) aggregating incident substation stress and transferring branch loading.
- **Global Pooling**: Graph-level representations via concatenated mean and max pooling generating a 128-dimensional latent state $\mathbf{z}_{\text{graph}} \in \mathbb{R}^{128}$ for P5 retrieval.

---

## 2. Experimental Results & Baseline Comparison

The models were evaluated on held-out test contingencies from the 8,778-scenario dataset (70% train, 15% validation, 15% test). The Cascade GNN was compared against classical tabular models (Random Forest and Logistic Regression):

| Metric | Random Forest Baseline | Logistic Regression | **Cascade GNN (Ours)** | Improvement |
|---|---|---|---|---|
| **Cascade ROC-AUC** | 0.9321 | 0.9321 | **0.9914** | **+5.93%** |
| **Cascade F1 Score** | 0.8015 | 0.8015 | **0.9886** | **+18.71%** |
| **Load Loss MAE (MW)** | 22.71 MW | 23.17 MW | **14.60 MW** | **-35.7% error** |
| **Inference Time / Cont.** | ~1.2 ms | ~0.4 ms | **~0.15 ms** | Batch scalable |

---

## 3. Calibration and Conformal Prediction (P3-4)

1. **Probability Calibration (Temperature Scaling)**:
   - Optimized temperature: $T = 0.678$ via validation NLL minimization.
   - **Expected Calibration Error (ECE)** dropped from **0.0242** down to **0.0007**, ensuring predicted line trip probabilities reflect true empirical frequencies.
2. **Conformal Prediction Intervals (Inductive Conformal Prediction)**:
   - Evaluated at a nominal 90% confidence level ($\alpha = 0.10$).
   - Conformal non-conformity quantile: $q = 6.60$ MW.
   - Empirical test coverage achieved: **91.2%**, satisfying the finite-sample coverage guarantee.

---

## 4. High-Throughput Screening (P3-5) & Explainability (P3-6)

- **Contingency Screening**: `ContingencyScreener` evaluated candidate N-1 and N-2 line outages at $>800$ contingencies/second, identifying top critical combinations in milliseconds.
- **Attribution & Critical Paths**: `CascadeExplainer` computes sensitivity gradients $\left|\frac{\partial \text{Risk}}{\partial \mathbf{e}}\right|$ to rank bottleneck branches leading to secondary overcurrent trips.
- **Handoff Artifacts**:
  - Model checkpoint: `data/models/cascade_gnn.pt`
  - Metrics record: `data/models/cascade_ml_metrics.json`
  - 128-dim embeddings: `data/processed/scenario_embeddings.parquet`
