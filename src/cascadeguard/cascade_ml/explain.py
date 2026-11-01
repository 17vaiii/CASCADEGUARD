# OWNER: P3 | STATUS: ACTIVE
"""Explainability and critical-line attribution for cascade predictions.

Implements P3-6:
  - Line attribution scores for why a cascade propagated
  - Identification of critical bottleneck transmission paths
"""

from __future__ import annotations

from typing import Any
import numpy as np
import torch
from torch_geometric.data import Data

from cascadeguard.cascade_ml.gnn import CascadeGNN


class CascadeExplainer:
    """Computes line attribution and critical propagation paths using gradient-based attribution."""

    def __init__(self, model: CascadeGNN):
        self.model = model

    def explain_scenario(self, data: Data, top_k_lines: int = 5) -> dict[str, Any]:
        """Explain the critical transmission elements driving the predicted cascade."""
        self.model.eval()

        # Clone line features and require gradient
        line_feats = data.line_features.clone().detach().requires_grad_(True)
        
        # Build edge_attr with cloned line features
        edge_attr = torch.cat([line_feats, line_feats], dim=0)

        out = self.model(
            x=data.x,
            edge_index=data.edge_index,
            edge_attr=edge_attr,
            line_from=data.edge_index[0, :data.num_lines],
            line_to=data.edge_index[1, :data.num_lines],
            line_features=line_feats,
        )

        # Target: overall risk (load loss + cascade size)
        target = out["load_loss_mw"].sum() + out["cascade_size"].sum() + out["has_cascade_logit"].sum()
        target.backward()

        # Gradient sensitivity: |dTarget / dLineFeature|
        grads = line_feats.grad.abs().sum(dim=-1).detach().cpu().numpy()
        probs = out["line_probs"].detach().cpu().numpy()

        initial_trips = set(np.where(data.line_features[:, 3].cpu().numpy() > 0.5)[0])

        critical_lines = []
        for line_idx, (grad, prob) in enumerate(zip(grads, probs)):
            if line_idx in initial_trips:
                continue  # Skip initial trigger lines
            # Attribution score combines model sensitivity and predicted trip probability
            attribution_score = float(grad * 100.0 + prob * 10.0)
            critical_lines.append({
                "line_index": int(line_idx),
                "attribution_score": round(attribution_score, 4),
                "failure_probability": round(float(prob), 4),
                "sensitivity": round(float(grad), 6),
            })

        critical_lines.sort(key=lambda x: x["attribution_score"], reverse=True)

        return {
            "initial_trips": list(initial_trips),
            "predicted_cascade_size": round(float(out["cascade_size"].item()), 2),
            "predicted_load_loss_mw": round(float(out["load_loss_mw"].item()), 2),
            "critical_propagation_lines": critical_lines[:top_k_lines],
        }
