# OWNER: P3 | STATUS: ACTIVE
"""Unit tests for Cascade ML modules (P3)."""

import numpy as np
import pytest
import torch

from cascadeguard.cascade_ml.baselines import TabularBaselines, extract_tabular_features
from cascadeguard.cascade_ml.calibration import ConformalIntervalPredictor, TemperatureScaler, compute_ece
from cascadeguard.cascade_ml.explain import CascadeExplainer
from cascadeguard.cascade_ml.gnn import CascadeGNN
from cascadeguard.cascade_ml.graph_builder import build_graph
from cascadeguard.cascade_ml.screening import ContingencyScreener


@pytest.fixture
def mock_snapshot():
    """Generates a small valid snapshot for testing."""
    num_buses = 5
    num_lines = 4
    return {
        "scenario_id": "test_scenario_001",
        "season": "summer",
        "load_scale": 1.1,
        "contingency_k": 1,
        "bus_ids": [f"bus_{i}" for i in range(num_buses)],
        "pre_bus_vm_pu": [1.02, 1.01, 0.99, 0.98, 1.00],
        "pre_bus_p_mw": [100.0, -20.0, -30.0, -25.0, -25.0],
        "pre_bus_q_mvar": [10.0, -5.0, -8.0, -6.0, -4.0],
        "line_ids": [f"line_{i}" for i in range(num_lines)],
        "line_from_bus": [0, 1, 2, 3],
        "line_to_bus": [1, 2, 3, 4],
        "pre_line_r_ohm": [0.5, 0.6, 0.4, 0.5],
        "pre_line_x_ohm": [2.0, 2.5, 1.8, 2.2],
        "pre_line_loading_pct": [65.0, 75.0, 85.0, 92.0],
        "initial_trips": [2],
        "failed_lines": [2, 3],
        "load_lost_mw": 25.0,
        "bengaluru_load_lost_mw": 25.0,
    }


def test_graph_builder(mock_snapshot):
    g = build_graph(mock_snapshot, include_targets=True)
    assert g.x.shape == (5, 4)
    assert g.edge_index.shape == (2, 8)  # 4 bidirectional lines = 8 edges
    assert g.edge_attr.shape == (8, 4)
    assert g.line_features.shape == (4, 4)
    assert g.y_lines.shape == (4,)
    assert g.y_lines[2].item() == 1.0
    assert g.y_lines[3].item() == 1.0
    assert g.y_lines[0].item() == 0.0
    assert g.y_load_loss.item() == 25.0
    assert g.y_cascade_size.item() == 2.0


def test_gnn_forward(mock_snapshot):
    g = build_graph(mock_snapshot, include_targets=True)
    model = CascadeGNN(hidden_dim=32, embedding_dim=64)
    out = model(
        x=g.x,
        edge_index=g.edge_index,
        edge_attr=g.edge_attr,
        line_from=g.edge_index[0, :g.num_lines],
        line_to=g.edge_index[1, :g.num_lines],
        line_features=g.line_features,
    )
    assert out["line_probs"].shape == (4,)
    assert torch.all((out["line_probs"] >= 0.0) & (out["line_probs"] <= 1.0))
    assert out["load_loss_mw"].item() >= 0.0
    assert out["cascade_size"].item() >= 0.0
    assert out["graph_embedding"].shape == (1, 64)


def test_temperature_scaling_and_ece():
    np.random.seed(42)
    logits = np.random.randn(200).astype(np.float32)
    labels = (logits > 0.2).astype(np.float32)

    scaler = TemperatureScaler()
    T = scaler.fit(logits, labels)
    assert T > 0.0

    probs = scaler.predict_proba(logits)
    assert len(probs) == 200
    assert np.all((probs >= 0.0) & (probs <= 1.0))

    ece = compute_ece(probs, labels, num_bins=5)
    assert 0.0 <= ece <= 1.0


def test_conformal_prediction():
    np.random.seed(42)
    y_true = np.random.uniform(10.0, 100.0, size=150)
    y_pred = y_true + np.random.normal(0.0, 5.0, size=150)

    conformal = ConformalIntervalPredictor(alpha=0.10)
    q = conformal.fit(y_pred[:100], y_true[:100])
    assert q > 0.0

    coverage = conformal.evaluate_coverage(y_pred[100:], y_true[100:])
    # Should achieve roughly ~90% coverage
    assert coverage >= 0.80


def test_contingency_screening(mock_snapshot):
    model = CascadeGNN(hidden_dim=16, embedding_dim=32)
    screener = ContingencyScreener(model=model)

    candidates = [[0], [1], [2], [3], [0, 1], [1, 2]]
    res = screener.screen_contingencies(mock_snapshot, candidates, top_k=3)

    assert res["total_screened"] == 6
    assert len(res["top_contingencies"]) == 3
    assert res["throughput_per_sec"] > 0.0
    # First item has highest risk
    assert res["top_contingencies"][0]["risk_score"] >= res["top_contingencies"][1]["risk_score"]


def test_cascade_explainer(mock_snapshot):
    g = build_graph(mock_snapshot, include_targets=True)
    model = CascadeGNN(hidden_dim=16, embedding_dim=32)
    explainer = CascadeExplainer(model=model)

    exp = explainer.explain_scenario(g, top_k_lines=2)
    assert "critical_propagation_lines" in exp
    assert len(exp["critical_propagation_lines"]) <= 2
    for item in exp["critical_propagation_lines"]:
        assert "line_index" in item
        assert "attribution_score" in item

