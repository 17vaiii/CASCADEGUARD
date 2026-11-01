# OWNER: P3 | STATUS: ACTIVE
"""Fast N-k contingency screening module using the trained Cascade GNN.

Implements P3-5:
  - Rapid candidate contingency evaluation (<1 ms per contingency)
  - Ranking by predicted severity (load loss and cascade extent)
  - Top-K recall evaluation against exhaustive AC power flow
"""

from __future__ import annotations

import time
from typing import Any, Mapping
import numpy as np
import torch
from torch_geometric.data import Batch

from cascadeguard.cascade_ml.gnn import CascadeGNN
from cascadeguard.cascade_ml.graph_builder import build_graph


class ContingencyScreener:
    """High-throughput N-k screening engine."""

    def __init__(self, model: CascadeGNN, device: str = "cpu"):
        self.model = model.to(device)
        self.model.eval()
        self.device = device

    def screen_contingencies(
        self,
        base_snapshot: Mapping[str, Any],
        candidate_trips: list[list[int]],
        top_k: int = 10,
        batch_size: int = 128,
    ) -> dict[str, Any]:
        """Screen a list of candidate line outages and return the top-K highest risk.
        
        Args:
          base_snapshot: Baseline pre-contingency grid snapshot.
          candidate_trips: List of initial line trip sets, e.g. [[0], [1], [0, 5], ...].
          top_k: Number of highest-risk contingencies to return.
          batch_size: Evaluation batch size.
        
        Returns:
          Dictionary with ranked results, elapsed time, and throughput (contingencies/sec).
        """
        t0 = time.perf_counter()
        results = []

        # Process in batches
        for i in range(0, len(candidate_trips), batch_size):
            chunk = candidate_trips[i : i + batch_size]
            graphs = []
            for trips in chunk:
                snap = dict(base_snapshot)
                snap["initial_trips"] = list(trips)
                g = build_graph(snap, include_targets=False)
                graphs.append(g)

            batch = Batch.from_data_list(graphs).to(self.device)
            
            with torch.no_grad():
                # Line indices for batch
                out = self.model(
                    x=batch.x,
                    edge_index=batch.edge_index,
                    edge_attr=batch.edge_attr,
                    line_from=batch.edge_index[0, :batch.num_lines.sum()],
                    line_to=batch.edge_index[1, :batch.num_lines.sum()],
                    line_features=batch.line_features,
                    batch=batch.batch,
                )

                load_loss_preds = out["load_loss_mw"].cpu().numpy().flatten()
                size_preds = out["cascade_size"].cpu().numpy().flatten()
                prob_preds = out["has_cascade_prob"].cpu().numpy().flatten()

            for j, trips in enumerate(chunk):
                risk_score = float(load_loss_preds[j] * 2.0 + size_preds[j] * 5.0 + prob_preds[j] * 10.0)
                results.append({
                    "trips": trips,
                    "risk_score": round(risk_score, 4),
                    "predicted_load_loss_mw": round(float(load_loss_preds[j]), 2),
                    "predicted_cascade_size": round(float(size_preds[j]), 2),
                    "has_cascade_prob": round(float(prob_preds[j]), 4),
                })

        elapsed = time.perf_counter() - t0
        throughput = len(candidate_trips) / max(elapsed, 1e-6)

        # Sort descending by risk score
        results.sort(key=lambda r: r["risk_score"], reverse=True)
        top_results = results[:top_k]

        return {
            "top_contingencies": top_results,
            "total_screened": len(candidate_trips),
            "elapsed_seconds": round(elapsed, 4),
            "throughput_per_sec": round(throughput, 1),
        }

    def evaluate_top_k_recall(
        self,
        predicted_rankings: list[list[int]],
        true_rankings: list[list[int]],
        k: int = 10,
    ) -> float:
        """Calculate Top-K recall: fraction of true top-K critical contingencies captured."""
        true_top = set(tuple(sorted(x)) for x in true_rankings[:k])
        pred_top = set(tuple(sorted(x)) for x in predicted_rankings[:k])
        if not true_top:
            return 1.0
        overlap = len(true_top.intersection(pred_top))
        return float(overlap / len(true_top))
