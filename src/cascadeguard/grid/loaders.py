# OWNER: P1 | STATUS: ACTIVE
"""Grid loaders for benchmark and transmission networks.
Supports standard IEEE benchmark networks (IEEE 14, IEEE 39, IEEE 118)
and validation gates for AC power flow convergence, voltage bounds, and line loading.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import logging
import pandapower as pp
import pandapower.networks as pn

logger = logging.getLogger(__name__)

SUPPORTED_GRIDS = {
    "ieee14": pn.case14,
    "ieee39": pn.case39,
    "ieee118": pn.case118,
}

@dataclass
class GridGateResult:
    """Outcome of validating base-case power flow on a network."""
    grid_id: str
    converged: bool
    v_min: float
    v_max: float
    v_violations: List[int] = field(default_factory=list)
    max_line_loading_pct: float = 0.0
    overloaded_lines: List[int] = field(default_factory=list)
    passed: bool = False
    rejection_reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


def load_grid(grid_id: str) -> pp.pandapowerNet:
    """Load a standard benchmark grid by ID.
    
    Args:
        grid_id: Identifier, e.g. 'ieee14', 'ieee39', 'ieee118'.
        
    Returns:
        pandapowerNet instance.
        
    Raises:
        ValueError: If grid_id is not supported.
    """
    key = grid_id.lower().replace("-", "").replace("_", "")
    if key not in SUPPORTED_GRIDS:
        raise ValueError(
            f"Unsupported grid '{grid_id}'. Available: {list(SUPPORTED_GRIDS.keys())}"
        )
    net = SUPPORTED_GRIDS[key]()
    net.name = grid_id
    return net


def run_power_flow(net: pp.pandapowerNet, algorithm: str = "nr", **kwargs) -> bool:
    """Run AC power flow on the pandapower network.
    
    Args:
        net: pandapower network.
        algorithm: Solver algorithm ('nr' for Newton-Raphson, 'bfsw', etc.).
        **kwargs: Additional parameters forwarded to pp.runpp().
        
    Returns:
        True if power flow converged, False otherwise.
    """
    try:
        pp.runpp(net, algorithm=algorithm, **kwargs)
        return bool(net.converged)
    except (pp.LoadflowNotConverged, Exception) as exc:
        logger.warning(f"Power flow failed to converge for network {getattr(net, 'name', 'unnamed')}: {exc}")
        return False


def validate_base_case_gate(
    net: pp.pandapowerNet,
    grid_id: str,
    v_min_limit: float = 0.90,
    v_max_limit: float = 1.10,
    max_loading_limit: float = 100.0,
) -> GridGateResult:
    """Base-case gate for any network:
    1. AC power flow converges.
    2. Voltages remain within [v_min_limit, v_max_limit] p.u.
    3. No intact-state line overloads exceeding max_loading_limit %.
    
    Logs and records rejected operating points with the reason.
    """
    converged = run_power_flow(net)
    if not converged:
        return GridGateResult(
            grid_id=grid_id,
            converged=False,
            v_min=0.0,
            v_max=0.0,
            passed=False,
            rejection_reason="AC power flow did not converge in base state.",
        )

    # Voltage checks
    vm = net.res_bus["vm_pu"]
    v_min = float(vm.min())
    v_max = float(vm.max())
    v_violations = net.res_bus[
        (net.res_bus["vm_pu"] < v_min_limit) | (net.res_bus["vm_pu"] > v_max_limit)
    ].index.tolist()

    # Line loading checks
    loading = net.res_line["loading_percent"]
    max_loading = float(loading.max()) if len(loading) > 0 else 0.0
    overloaded_lines = net.res_line[
        net.res_line["loading_percent"] > max_loading_limit
    ].index.tolist()

    passed = True
    reasons = []

    if v_violations:
        passed = False
        reasons.append(
            f"Voltage violations at buses {v_violations} (bounds: [{v_min_limit}, {v_max_limit}], observed: [{v_min:.3f}, {v_max:.3f}])"
        )
    if overloaded_lines:
        passed = False
        reasons.append(
            f"Overloaded lines {overloaded_lines} (max limit: {max_loading_limit}%, observed: {max_loading:.1f}%)"
        )

    rejection_reason = "; ".join(reasons) if not passed else None

    return GridGateResult(
        grid_id=grid_id,
        converged=True,
        v_min=v_min,
        v_max=v_max,
        v_violations=v_violations,
        max_line_loading_pct=max_loading,
        overloaded_lines=overloaded_lines,
        passed=passed,
        rejection_reason=rejection_reason,
        details={
            "bus_count": len(net.bus),
            "line_count": len(net.line),
            "gen_count": len(net.gen) + len(net.ext_grid),
            "load_count": len(net.load),
            "total_load_mw": float(net.load["p_mw"].sum()) if len(net.load) else 0.0,
        },
    )
