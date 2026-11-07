# OWNER: P4 | STATUS: ACTIVE
"""P4-6: graph refinement over the distribution topology (feeder -> DT -> consumers).

One graph holds every feeder, DT and consumer node; edges follow the electrical hierarchy
(both directions). GraphSAGE message passing lets the DT / feeder energy-balance residual
inform the consumers below it and lets neighbouring consumers' evidence be compared.
Consumer nodes in the training split carry the labels; DT and feeder nodes are unlabelled.

Node features (zero-padded into one vector):
``[consumer behaviour + tamper + unsupervised scores | DT residual | feeder residual | type one-hot]``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score
from sklearn.preprocessing import RobustScaler
from torch_geometric.data import Data
from torch_geometric.nn import SAGEConv

from cascadeguard.theft import load_config


class TheftGraphSAGE(nn.Module):
    def __init__(self, in_dim: int, hidden: int = 32, layers: int = 2, dropout: float = 0.2):
        super().__init__()
        dims = [in_dim] + [hidden] * layers
        self.convs = nn.ModuleList(SAGEConv(dims[i], dims[i + 1]) for i in range(layers))
        self.skip = nn.Linear(in_dim, hidden)
        self.head = nn.Linear(hidden, 1)
        self.dropout = dropout

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        h = x
        for conv in self.convs:
            h = F.dropout(F.relu(conv(h, edge_index)), p=self.dropout, training=self.training)
        return self.head(h + self.skip(x)).squeeze(-1)


def build_theft_graph(consumers: pd.DataFrame, consumer_x: pd.DataFrame,
                      dt_summary: pd.DataFrame | None, feeder_summary: pd.DataFrame,
                      dts: pd.DataFrame, feeders: pd.DataFrame) -> tuple[Data, dict[str, Any]]:
    """Assemble the PyG graph. ``consumer_x`` is indexed by consumer_id (numeric columns only)."""
    cx = consumer_x.reindex(consumers.consumer_id)
    prep = (SimpleImputer(strategy="median"), RobustScaler())
    xc = prep[1].fit_transform(prep[0].fit_transform(cx.to_numpy(dtype=float)))
    xc = np.clip(xc, -8, 8)
    n_c, d_c = xc.shape
    dsum = dt_summary.set_index("node_id") if dt_summary is not None else pd.DataFrame()
    fsum = feeder_summary.set_index("node_id")
    n_d, n_f = len(dts), len(feeders)

    def log_z(v: np.ndarray) -> np.ndarray:
        return np.sign(v) * np.log1p(np.abs(v))

    xd = np.zeros((n_d, 3))
    if len(dsum):
        xd[:, 0] = log_z(dsum.z.reindex(dts.dt_id).fillna(0.0).to_numpy())
        xd[:, 1] = dsum.peak_change_pct.reindex(dts.dt_id).fillna(0.0).to_numpy() / 5.0
    xd[:, 2] = dts.dt_id.isin(dsum.index).astype(float).to_numpy() if len(dsum) else 0.0
    xf = np.zeros((n_f, 2))
    xf[:, 0] = log_z(fsum.z.reindex(feeders.feeder_id).fillna(0.0).to_numpy())
    xf[:, 1] = fsum.peak_change_pct.reindex(feeders.feeder_id).fillna(0.0).to_numpy() / 5.0

    dim = d_c + 3 + 2 + 3
    x = np.zeros((n_c + n_d + n_f, dim), dtype=np.float32)
    x[:n_c, :d_c] = xc
    x[n_c:n_c + n_d, d_c:d_c + 3] = xd
    x[n_c + n_d:, d_c + 3:d_c + 5] = xf
    x[:n_c, -3] = 1.0
    x[n_c:n_c + n_d, -2] = 1.0
    x[n_c + n_d:, -1] = 1.0

    dt_pos = {d: n_c + i for i, d in enumerate(dts.dt_id)}
    f_pos = {f: n_c + n_d + i for i, f in enumerate(feeders.feeder_id)}
    src = list(range(n_c)) + [dt_pos[d] for d in dts.dt_id]
    dst = [dt_pos[d] for d in consumers.dt_id] + [f_pos[f] for f in dts.feeder_id]
    edge_index = torch.tensor([src + dst, dst + src], dtype=torch.long)
    data = Data(x=torch.tensor(x), edge_index=edge_index)
    return data, {"n_consumers": n_c, "dim": dim}


def train_graph_model(data: Data, n_consumers: int, y: np.ndarray, split: np.ndarray,
                      config: dict[str, Any] | None = None, seed: int = 42) -> tuple[np.ndarray, dict[str, Any]]:
    """Train on train consumers, early-stop on validation PR-AUC; return probabilities for all consumers."""
    cfg = (config or load_config())["graph"]
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = TheftGraphSAGE(data.num_features, int(cfg["hidden"]), int(cfg["layers"]), float(cfg["dropout"]))
    opt = torch.optim.Adam(model.parameters(), lr=float(cfg["lr"]), weight_decay=5e-4)
    y_t = torch.tensor(np.asarray(y, dtype=np.float32))
    tr = torch.tensor(split == "train")
    va = split == "validation"
    pos_w = torch.tensor([(1 - y[split == "train"].mean()) / max(y[split == "train"].mean(), 1e-3)])
    best, best_state, best_epoch, patience = -1.0, None, 0, 0
    for epoch in range(int(cfg["epochs"])):
        model.train()
        opt.zero_grad()
        logits = model(data.x, data.edge_index)[:n_consumers]
        loss = F.binary_cross_entropy_with_logits(logits[tr], y_t[tr], pos_weight=pos_w)
        loss.backward()
        opt.step()
        if epoch % 5 == 0:
            model.eval()
            with torch.no_grad():
                p = torch.sigmoid(model(data.x, data.edge_index)[:n_consumers]).numpy()
            ap = average_precision_score(y[va], p[va]) if y[va].sum() else 0.0
            if ap > best:
                best, best_epoch, patience = ap, epoch, 0
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
            else:
                patience += 1
                if patience >= 12:
                    break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        prob = torch.sigmoid(model(data.x, data.edge_index)[:n_consumers]).numpy()
    return prob, {"best_val_pr_auc": float(best), "best_epoch": int(best_epoch)}
