# OWNER: P3 | STATUS: ACTIVE
"""Graph builder module converting cascade grid snapshots into PyTorch Geometric Data objects.

Conforms to contracts/graph_tensor_format.md.
"""

from __future__ import annotations

from typing import Any, Mapping
import numpy as np
import torch
from torch_geometric.data import Data


def build_graph(
    record: Mapping[str, Any],
    include_targets: bool = True,
) -> Data:
    """Convert a cascade scenario record or pre-contingency snapshot into a PyG Data graph.
    
    Node Features (x) of shape [num_buses, 4]:
      0: vm_pu (voltage magnitude in p.u., ~1.0)
      1: p_mw / 100.0 (normalized active power injection)
      2: q_mvar / 100.0 (normalized reactive power injection)
      3: is_slack (1.0 for bus 0 slack / generator, else 0.0)

    Edge Index of shape [2, 2 * num_lines] (bidirectional transmission grid).

    Edge Features (edge_attr) of shape [2 * num_lines, 4]:
      0: r_ohm / 10.0 (normalized resistance)
      1: x_ohm / 50.0 (normalized reactance)
      2: loading_pct / 100.0 (pre-contingency line loading ratio)
      3: is_initial_trip (1.0 if this line was initially tripped at t=0, else 0.0)
    """
    raw_bus_ids = record.get("bus_ids")
    num_buses = len(raw_bus_ids) if raw_bus_ids is not None and len(raw_bus_ids) > 0 else 39
    
    raw_vm = record.get("pre_bus_vm_pu")
    vm_pu = np.asarray(raw_vm if raw_vm is not None else np.ones(num_buses, dtype=np.float32), dtype=np.float32)

    raw_p = record.get("pre_bus_p_mw")
    p_mw = np.asarray(raw_p if raw_p is not None else np.zeros(num_buses, dtype=np.float32), dtype=np.float32)

    raw_q = record.get("pre_bus_q_mvar")
    q_mvar = np.asarray(raw_q if raw_q is not None else np.zeros(num_buses, dtype=np.float32), dtype=np.float32)

    is_slack = np.zeros(num_buses, dtype=np.float32)
    is_slack[0] = 1.0  # Sharavathi slack bus (km 0)

    x_nodes = np.column_stack([
        vm_pu,
        p_mw / 100.0,
        q_mvar / 100.0,
        is_slack,
    ])
    x_tensor = torch.tensor(x_nodes, dtype=torch.float32)

    raw_from = record.get("line_from_bus")
    line_from = np.asarray(raw_from if raw_from is not None else [], dtype=np.int64)

    raw_to = record.get("line_to_bus")
    line_to = np.asarray(raw_to if raw_to is not None else [], dtype=np.int64)
    num_lines = len(line_from)

    raw_r = record.get("pre_line_r_ohm")
    r_ohm = np.asarray(raw_r if raw_r is not None else np.zeros(num_lines, dtype=np.float32), dtype=np.float32)

    raw_x = record.get("pre_line_x_ohm")
    x_ohm = np.asarray(raw_x if raw_x is not None else np.ones(num_lines, dtype=np.float32), dtype=np.float32)

    raw_loading = record.get("pre_line_loading_pct")
    loading_pct = np.asarray(raw_loading if raw_loading is not None else np.zeros(num_lines, dtype=np.float32), dtype=np.float32)

    raw_trips = record.get("initial_trips")
    initial_trips = set(raw_trips) if raw_trips is not None else set()
    is_tripped = np.array([1.0 if i in initial_trips else 0.0 for i in range(num_lines)], dtype=np.float32)

    base_line_feats = np.column_stack([
        r_ohm / 10.0,
        x_ohm / 50.0,
        loading_pct / 100.0,
        is_tripped,
    ])

    u = np.concatenate([line_from, line_to])
    v = np.concatenate([line_to, line_from])
    edge_index = torch.tensor(np.stack([u, v], axis=0), dtype=torch.long)

    edge_attr_arr = np.concatenate([base_line_feats, base_line_feats], axis=0)
    edge_attr = torch.tensor(edge_attr_arr, dtype=torch.float32)

    data = Data(
        x=x_tensor,
        edge_index=edge_index,
        edge_attr=edge_attr,
        num_nodes=num_buses,
    )
    data.line_features = torch.tensor(base_line_feats, dtype=torch.float32)
    data.num_lines = num_lines
    data.num_buses = num_buses

    if include_targets and "failed_lines" in record:
        raw_failed = record.get("failed_lines")
        failed_set = set(raw_failed) if raw_failed is not None else set()
        y_lines = np.array([1.0 if i in failed_set else 0.0 for i in range(num_lines)], dtype=np.float32)
        data.y_lines = torch.tensor(y_lines, dtype=torch.float32)
        
        load_lost = float(record.get("bengaluru_load_lost_mw", record.get("load_lost_mw", 0.0)))
        data.y_load_loss = torch.tensor([load_lost], dtype=torch.float32)
        data.y_cascade_size = torch.tensor([float(len(failed_set))], dtype=torch.float32)
        data.y_has_cascade = torch.tensor([1.0 if len(failed_set) > len(initial_trips) else 0.0], dtype=torch.float32)

    return data
