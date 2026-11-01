# OWNER: P3 | STATUS: ACTIVE
"""Graph embeddings export module for case-based retrieval in P5.

Implements P3-8:
  - Generates 128-dim scenario embeddings from the trained GNN
  - Exports embeddings to Parquet for ingestion into Qdrant vector store
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
import pandas as pd
import torch
from tqdm import tqdm

from cascadeguard.cascade_ml.gnn import CascadeGNN
from cascadeguard.cascade_ml.graph_builder import build_graph


def export_scenario_embeddings(
    dataset_path: str = "data/processed/cascade_dataset.parquet",
    model_path: str = "data/models/cascade_gnn.pt",
    output_path: str = "data/processed/scenario_embeddings.parquet",
    batch_size: int = 128,
    limit: int | None = None,
) -> pd.DataFrame:
    """Compute and save 128-dim graph embeddings for past cascade cases."""
    df = pd.read_parquet(dataset_path)
    if limit is not None:
        df = df.head(limit)

    device = "cpu"
    model = CascadeGNN().to(device)
    if Path(model_path).exists():
        checkpoint = torch.load(model_path, map_location=device, weights_only=True)
        model.load_state_dict(checkpoint.get("model_state", checkpoint))
    model.eval()

    embeddings = []
    print(f"Exporting embeddings for {len(df)} scenarios...")

    with torch.no_grad():
        for _, row in tqdm(df.iterrows(), total=len(df), desc="Embedding"):
            g = build_graph(row.to_dict(), include_targets=False)
            emb = model.get_embedding(g).cpu().numpy().tolist()
            embeddings.append(emb)

    df_out = pd.DataFrame({
        "scenario_id": df["scenario_id"].values,
        "season": df["season"].values,
        "load_scale": df["load_scale"].values,
        "contingency_k": df["contingency_k"].values,
        "initial_trips": df["initial_trips"].values,
        "failed_lines": df["failed_lines"].values,
        "load_lost_mw": df.get("bengaluru_load_lost_mw", df.get("load_lost_mw", 0.0)).values,
        "embedding": embeddings,
    })

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(output_path)
    print(f"Successfully exported {len(df_out)} embeddings to {output_path}")
    return df_out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/processed/cascade_dataset.parquet")
    parser.add_argument("--model", default="data/models/cascade_gnn.pt")
    parser.add_argument("--output", default="data/processed/scenario_embeddings.parquet")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    export_scenario_embeddings(args.dataset, args.model, args.output, limit=args.limit)


if __name__ == "__main__":
    main()
