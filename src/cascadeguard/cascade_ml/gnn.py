# OWNER: P3 | STATUS: ACTIVE
"""Cascade GNN architecture for transmission grid contingency risk estimation.

Predicts:
  1. Per-line failure probabilities (edge-level classification)
  2. Cascade extent (total failed lines count)
  3. Load loss in MW (specifically at Bengaluru/Peenya end)
  4. 128-dimensional graph embedding for P5 case retrieval
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import MessagePassing, global_mean_pool, global_max_pool


class GridEdgeConv(MessagePassing):
    """Edge-conditioned message passing layer for transmission networks.
    
    Transfers information between substations conditioned on line impedance & loading.
    """
    def __init__(self, node_dim: int, edge_dim: int, out_dim: int):
        super().__init__(aggr="add")
        self.msg_mlp = nn.Sequential(
            nn.Linear(node_dim + edge_dim, out_dim),
            nn.LayerNorm(out_dim),
            nn.ReLU(),
            nn.Linear(out_dim, out_dim),
        )
        self.update_mlp = nn.Sequential(
            nn.Linear(node_dim + out_dim, out_dim),
            nn.LayerNorm(out_dim),
            nn.ReLU(),
        )

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor, edge_attr: torch.Tensor) -> torch.Tensor:
        return self.propagate(edge_index, x=x, edge_attr=edge_attr)

    def message(self, x_j: torch.Tensor, edge_attr: torch.Tensor) -> torch.Tensor:
        # x_j is the neighbor node representation
        msg_input = torch.cat([x_j, edge_attr], dim=-1)
        return self.msg_mlp(msg_input)

    def update(self, aggr_out: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
        update_input = torch.cat([x, aggr_out], dim=-1)
        return self.update_mlp(update_input)


class CascadeGNN(nn.Module):
    """Multi-task Cascade Risk GNN."""
    def __init__(
        self,
        node_in_dim: int = 4,
        edge_in_dim: int = 4,
        hidden_dim: int = 64,
        num_layers: int = 3,
        embedding_dim: int = 128,
    ):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.embedding_dim = embedding_dim

        # Input projections
        self.node_encoder = nn.Sequential(
            nn.Linear(node_in_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )
        self.edge_encoder = nn.Sequential(
            nn.Linear(edge_in_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )

        # Message passing layers
        self.convs = nn.ModuleList([
            GridEdgeConv(hidden_dim, hidden_dim, hidden_dim)
            for _ in range(num_layers)
        ])

        # Line failure prediction head: [h_u, h_v, e_uv] -> 1 logit
        self.line_classifier = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

        # Graph pooling & representation: mean + max pooling (hidden_dim * 2 -> embedding_dim)
        self.graph_proj = nn.Sequential(
            nn.Linear(hidden_dim * 2, embedding_dim),
            nn.LayerNorm(embedding_dim),
            nn.ReLU(),
        )

        # Graph-level multi-task heads
        self.head_cascade_size = nn.Sequential(
            nn.Linear(embedding_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )
        self.head_load_loss = nn.Sequential(
            nn.Linear(embedding_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )
        self.head_has_cascade = nn.Sequential(
            nn.Linear(embedding_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
        line_from: torch.Tensor,
        line_to: torch.Tensor,
        line_features: torch.Tensor,
        batch: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """Forward pass.
        
        Returns:
          - line_logits: [num_lines] or [B * num_lines]
          - cascade_size: [B, 1]
          - load_loss_mw: [B, 1]
          - has_cascade_logit: [B, 1]
          - graph_embedding: [B, 128]
        """
        if batch is None:
            batch = torch.zeros(x.size(0), dtype=torch.long, device=x.device)

        h_node = self.node_encoder(x)
        h_edge = self.edge_encoder(edge_attr)

        for conv in self.convs:
            h_node = h_node + conv(h_node, edge_index, h_edge)

        # Graph embedding via global pooling
        mean_p = global_mean_pool(h_node, batch)
        max_p = global_max_pool(h_node, batch)
        graph_emb = self.graph_proj(torch.cat([mean_p, max_p], dim=-1))

        # Predict graph-level outcomes
        cascade_size = F.relu(self.head_cascade_size(graph_emb))
        load_loss = F.relu(self.head_load_loss(graph_emb))
        has_cascade = self.head_has_cascade(graph_emb)

        # Line failure logits: for each physical line between line_from and line_to
        h_u = h_node[line_from]
        h_v = h_node[line_to]
        h_line_base = self.edge_encoder(line_features)
        line_cat = torch.cat([h_u, h_v, h_line_base], dim=-1)
        line_logits = self.line_classifier(line_cat).squeeze(-1)

        return {
            "line_logits": line_logits,
            "line_probs": torch.sigmoid(line_logits),
            "cascade_size": cascade_size,
            "load_loss_mw": load_loss,
            "has_cascade_logit": has_cascade,
            "has_cascade_prob": torch.sigmoid(has_cascade),
            "graph_embedding": graph_emb,
        }

    def get_embedding(self, data) -> torch.Tensor:
        """Extract the 128-dim graph embedding for a single graph instance."""
        self.eval()
        with torch.no_grad():
            res = self.forward(
                x=data.x,
                edge_index=data.edge_index,
                edge_attr=data.edge_attr,
                line_from=data.edge_index[0, :data.num_lines],
                line_to=data.edge_index[1, :data.num_lines],
                line_features=data.line_features,
            )
            return res["graph_embedding"].squeeze(0)
