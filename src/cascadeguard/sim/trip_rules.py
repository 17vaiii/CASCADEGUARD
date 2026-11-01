# OWNER: P1 | STATUS: ACTIVE
"""Overcurrent relay models and tripping threshold rules."""

from __future__ import annotations

import pandapower as pp


def identify_overloaded_lines(
    net: pp.pandapowerNet,
    loading_threshold: float = 100.0,
) -> dict[int, float]:
    """Find lines whose loading percent exceeds the overcurrent relay trip threshold."""
    overloaded: dict[int, float] = {}
    if not hasattr(net, "res_line") or net.res_line.empty:
        return overloaded

    for idx in net.line.index:
        if net.line.at[idx, "in_service"]:
            loading = float(net.res_line.at[idx, "loading_percent"])
            if loading >= loading_threshold:
                overloaded[int(idx)] = round(loading, 2)

    return overloaded
