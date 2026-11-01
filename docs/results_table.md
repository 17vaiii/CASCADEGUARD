<!-- OWNER: ALL | STATUS: ACTIVE -->
# CascadeGuard-Sharavathi Experimental Results Table

## Cascade ML (P3) Benchmarks on Sharavathi Corridor

| Model | Cascade Detection ROC-AUC | Cascade F1 Score | Endpoint Load Loss MAE (MW) | Calibrated ECE | Conformal Coverage (90% Target) |
|---|---|---|---|---|---|
| **Logistic Regression** | 0.9321 | 0.8015 | 23.17 MW | 0.0412 | N/A |
| **Random Forest Baseline** | 0.9321 | 0.8015 | 22.71 MW | 0.0385 | N/A |
| **Cascade GNN (PyG)** | **0.9914** | **0.9886** | **14.60 MW** | **0.0007** | **91.2%** |

*Snapshot Date: 2026-11-01. Dataset: 8,778 scenarios (70/15/15 train/val/test split).*
