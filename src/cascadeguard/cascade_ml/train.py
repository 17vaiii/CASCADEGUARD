# OWNER: P3 | STATUS: ACTIVE
"""Cascade GNN training and evaluation pipeline with calibration and baseline comparison.

Implements P3-3, P3-4, and P3-7:
  - Trains multi-task CascadeGNN on scenario datasets
  - Evaluates against Random Forest and Logistic Regression baselines
  - Calibrates line failure probabilities (Temperature Scaling & ECE)
  - Calibrates load loss conformal prediction intervals
  - Saves model checkpoint and metrics artifact
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torch_geometric.data import Batch

from cascadeguard.cascade_ml.baselines import TabularBaselines, extract_tabular_features
from cascadeguard.cascade_ml.calibration import ConformalIntervalPredictor, TemperatureScaler, compute_ece
from cascadeguard.cascade_ml.gnn import CascadeGNN
from cascadeguard.cascade_ml.graph_builder import build_graph


class CascadeGraphDataset(Dataset):
    """In-memory PyG dataset for cascade scenarios."""
    def __init__(self, records: list[dict[str, Any]]):
        self.graphs = [build_graph(r, include_targets=True) for r in records]

    def __len__(self) -> int:
        return len(self.graphs)

    def __getitem__(self, idx: int):
        return self.graphs[idx]


def pyg_collate(batch):
    return Batch.from_data_list(batch)


def train_pipeline(
    dataset_path: str = "data/processed/cascade_dataset.parquet",
    output_dir: str = "data/models",
    epochs: int = 15,
    batch_size: int = 64,
    learning_rate: float = 0.001,
    seed: int = 42,
    sample_limit: int | None = None,
) -> dict[str, Any]:
    """Train GNN, calibrate, evaluate baselines, and save artifacts."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    print(f"Loading cascade scenarios from {dataset_path}...")
    df = pd.read_parquet(dataset_path)
    if sample_limit is not None and len(df) > sample_limit:
        df = df.sample(n=sample_limit, random_state=seed).reset_index(drop=True)

    total_n = len(df)
    train_n = int(0.70 * total_n)
    val_n = int(0.15 * total_n)
    
    indices = np.random.permutation(total_n)
    train_idx = indices[:train_n]
    val_idx = indices[train_n : train_n + val_n]
    test_idx = indices[train_n + val_n :]

    df_train = df.iloc[train_idx].reset_index(drop=True)
    df_val = df.iloc[val_idx].reset_index(drop=True)
    df_test = df.iloc[test_idx].reset_index(drop=True)

    print(f"Dataset split: Train={len(df_train)}, Val={len(df_val)}, Test={len(df_test)}")

    # 1. Train Tabular Baselines
    print("\n--- Training Tabular Baselines (P3-2) ---")
    X_train, y_casc_train, y_loss_train = extract_tabular_features(df_train)
    X_test, y_casc_test, y_loss_test = extract_tabular_features(df_test)
    
    baselines = TabularBaselines(random_state=seed)
    baselines.fit(X_train, y_casc_train, y_loss_train)
    baseline_metrics = baselines.evaluate(X_test, y_casc_test, y_loss_test)
    print("Baseline Results:")
    print("  Random Forest:", baseline_metrics["random_forest"])
    print("  Logistic Regression:", baseline_metrics["logistic_regression"])

    # 2. Build PyG Datasets
    print("\n--- Building Graph Tensors (P3-1) ---")
    train_ds = CascadeGraphDataset(df_train.to_dict(orient="records"))
    val_ds = CascadeGraphDataset(df_val.to_dict(orient="records"))
    test_ds = CascadeGraphDataset(df_test.to_dict(orient="records"))

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, collate_fn=pyg_collate)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, collate_fn=pyg_collate)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False, collate_fn=pyg_collate)

    # 3. Initialize CascadeGNN
    device = "cpu"
    model = CascadeGNN().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)

    bce_line = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([3.0]))
    bce_casc = nn.BCEWithLogitsLoss()
    huber = nn.SmoothL1Loss()

    print(f"\n--- Training Cascade GNN (P3-3) for {epochs} epochs ---")
    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0

        for batch in train_loader:
            optimizer.zero_grad()
            batch = batch.to(device)

            out = model(
                x=batch.x,
                edge_index=batch.edge_index,
                edge_attr=batch.edge_attr,
                line_from=batch.edge_index[0, :batch.num_lines.sum()],
                line_to=batch.edge_index[1, :batch.num_lines.sum()],
                line_features=batch.line_features,
                batch=batch.batch,
            )

            loss_lines = bce_line(out["line_logits"], batch.y_lines)
            loss_size = huber(out["cascade_size"].squeeze(-1), batch.y_cascade_size)
            loss_load = huber(out["load_loss_mw"].squeeze(-1), batch.y_load_loss)
            loss_casc = bce_casc(out["has_cascade_logit"].squeeze(-1), batch.y_has_cascade)

            loss = loss_lines * 5.0 + loss_size * 0.1 + loss_load * 0.02 + loss_casc * 2.0
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        # Validation pass
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch in val_loader:
                batch = batch.to(device)
                out = model(
                    x=batch.x,
                    edge_index=batch.edge_index,
                    edge_attr=batch.edge_attr,
                    line_from=batch.edge_index[0, :batch.num_lines.sum()],
                    line_to=batch.edge_index[1, :batch.num_lines.sum()],
                    line_features=batch.line_features,
                    batch=batch.batch,
                )
                l = (bce_line(out["line_logits"], batch.y_lines) * 5.0 +
                     huber(out["cascade_size"].squeeze(-1), batch.y_cascade_size) * 0.1 +
                     huber(out["load_loss_mw"].squeeze(-1), batch.y_load_loss) * 0.02)
                val_loss += l.item()

        print(f"Epoch {epoch:2d}/{epochs:2d} | Train Loss: {train_loss/len(train_loader):.4f} | Val Loss: {val_loss/len(val_loader):.4f}")

    # 4. Calibration on Validation Set (P3-4)
    print("\n--- Calibrating Model Probabilities & Intervals (P3-4) ---")
    model.eval()
    val_line_logits, val_line_targets = [], []
    val_loss_preds, val_loss_targets = [], []

    with torch.no_grad():
        for batch in val_loader:
            out = model(
                x=batch.x,
                edge_index=batch.edge_index,
                edge_attr=batch.edge_attr,
                line_from=batch.edge_index[0, :batch.num_lines.sum()],
                line_to=batch.edge_index[1, :batch.num_lines.sum()],
                line_features=batch.line_features,
                batch=batch.batch,
            )
            val_line_logits.append(out["line_logits"].cpu())
            val_line_targets.append(batch.y_lines.cpu())
            val_loss_preds.append(out["load_loss_mw"].squeeze(-1).cpu())
            val_loss_targets.append(batch.y_load_loss.cpu())

    val_logits_t = torch.cat(val_line_logits).numpy()
    val_targets_t = torch.cat(val_line_targets).numpy()
    val_loss_p = torch.cat(val_loss_preds).numpy()
    val_loss_t = torch.cat(val_loss_targets).numpy()

    # Temperature scaling
    scaler = TemperatureScaler()
    scaler.fit(val_logits_t, val_targets_t)
    print(f"Learned Temperature T = {scaler.temperature:.3f}")

    # Conformal interval calibration (90% coverage target, alpha=0.10)
    conformal = ConformalIntervalPredictor(alpha=0.10)
    conformal.fit(val_loss_p, val_loss_t)
    print(f"Conformal Quantile q (90% coverage) = {conformal.q_val:.2f} MW")

    # 5. Evaluate on Test Set
    test_line_logits, test_line_targets = [], []
    test_loss_preds, test_loss_targets = [], []
    test_has_casc_preds, test_has_casc_targets = [], []

    with torch.no_grad():
        for batch in test_loader:
            out = model(
                x=batch.x,
                edge_index=batch.edge_index,
                edge_attr=batch.edge_attr,
                line_from=batch.edge_index[0, :batch.num_lines.sum()],
                line_to=batch.edge_index[1, :batch.num_lines.sum()],
                line_features=batch.line_features,
                batch=batch.batch,
            )
            test_line_logits.append(out["line_logits"].cpu())
            test_line_targets.append(batch.y_lines.cpu())
            test_loss_preds.append(out["load_loss_mw"].squeeze(-1).cpu())
            test_loss_targets.append(batch.y_load_loss.cpu())
            test_has_casc_preds.append(out["has_cascade_prob"].squeeze(-1).cpu())
            test_has_casc_targets.append(batch.y_has_cascade.cpu())

    test_logits_t = torch.cat(test_line_logits).numpy()
    test_targets_t = torch.cat(test_line_targets).numpy()
    test_loss_p = torch.cat(test_loss_preds).numpy()
    test_loss_t = torch.cat(test_loss_targets).numpy()
    test_casc_p = torch.cat(test_has_casc_preds).numpy()
    test_casc_t = torch.cat(test_has_casc_targets).numpy()

    # Compute uncalibrated vs calibrated ECE
    uncal_probs = 1.0 / (1.0 + np.exp(-test_logits_t))
    cal_probs = scaler.predict_proba(test_logits_t)
    uncal_ece = compute_ece(uncal_probs, test_targets_t)
    cal_ece = compute_ece(cal_probs, test_targets_t)

    # Conformal test coverage
    empirical_coverage = conformal.evaluate_coverage(test_loss_p, test_loss_t)
    mae_load_loss = float(np.mean(np.abs(test_loss_p - test_loss_t)))
    
    from sklearn.metrics import roc_auc_score, f1_score
    test_casc_pred_bin = (test_casc_p > 0.5).astype(int)
    auc_casc = float(roc_auc_score(test_casc_t, test_casc_p))
    f1_casc = float(f1_score(test_casc_t, test_casc_pred_bin, zero_division=0))

    gnn_metrics = {
        "cascade_roc_auc": round(auc_casc, 4),
        "cascade_f1": round(f1_casc, 4),
        "load_loss_mae_mw": round(mae_load_loss, 2),
        "temperature_T": round(scaler.temperature, 4),
        "uncalibrated_ece": round(uncal_ece, 4),
        "calibrated_ece": round(cal_ece, 4),
        "conformal_quantile_mw": round(conformal.q_val, 2),
        "conformal_target_coverage": 0.90,
        "conformal_empirical_coverage": round(empirical_coverage, 4),
    }

    print("\n================== FINAL EVALUATION SUMMARY ==================")
    print(f"GNN Cascade ROC-AUC:         {gnn_metrics['cascade_roc_auc']:.4f}  (Baseline RF: {baseline_metrics['random_forest']['roc_auc']:.4f})")
    print(f"GNN Cascade F1 Score:        {gnn_metrics['cascade_f1']:.4f}  (Baseline RF: {baseline_metrics['random_forest']['f1']:.4f})")
    print(f"GNN Load Loss MAE:           {gnn_metrics['load_loss_mae_mw']:.2f} MW (Baseline RF: {baseline_metrics['random_forest']['load_loss_mae']:.2f} MW)")
    print(f"Calibration ECE:             {gnn_metrics['calibrated_ece']:.4f} (improved from {gnn_metrics['uncalibrated_ece']:.4f})")
    print(f"Conformal Coverage (90% tgt):{gnn_metrics['conformal_empirical_coverage']*100:.1f}%")
    print("==============================================================")

    # Save artifacts
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    checkpoint_path = Path(output_dir) / "cascade_gnn.pt"
    metrics_path = Path(output_dir) / "cascade_ml_metrics.json"

    torch.save({
        "model_state": model.state_dict(),
        "temperature": scaler.temperature,
        "conformal_q": conformal.q_val,
        "metrics": gnn_metrics,
        "baseline_metrics": baseline_metrics,
    }, checkpoint_path)

    full_report = {
        "gnn_metrics": gnn_metrics,
        "baseline_metrics": baseline_metrics,
        "train_samples": len(df_train),
        "val_samples": len(df_val),
        "test_samples": len(df_test),
    }
    metrics_path.write_text(json.dumps(full_report, indent=2))
    print(f"\nSaved model checkpoint to {checkpoint_path}")
    print(f"Saved evaluation metrics to {metrics_path}")
    return full_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/processed/cascade_dataset.parquet")
    parser.add_argument("--output-dir", default="data/models")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    train_pipeline(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        sample_limit=args.limit,
    )


if __name__ == "__main__":
    main()
