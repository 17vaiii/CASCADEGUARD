# OWNER: P1 | STATUS: ACTIVE
"""Islanding detection and load shedding balancing for electrical transmission splits."""

from __future__ import annotations

import networkx as nx
import pandapower as pp


def detect_islands(net: pp.pandapowerNet) -> list[set[int]]:
    """Find connected bus components (islands) formed by in-service transmission lines."""
    g = nx.Graph()
    for idx in net.bus.index:
        if net.bus.at[idx, "in_service"]:
            g.add_node(int(idx))

    for idx in net.line.index:
        if net.line.at[idx, "in_service"]:
            u = int(net.line.at[idx, "from_bus"])
            v = int(net.line.at[idx, "to_bus"])
            g.add_edge(u, v)

    return [set(c) for c in nx.connected_components(g)]


def island_has_generation(net: pp.pandapowerNet, island: set[int]) -> bool:
    """Check if an island contains an active external grid or generation slack bus."""
    for idx in net.ext_grid.index:
        if net.ext_grid.at[idx, "in_service"] and int(net.ext_grid.at[idx, "bus"]) in island:
            return True
    return False


def shed_island_loads(net: pp.pandapowerNet, island: set[int]) -> tuple[float, list[int]]:
    """Disconnect unpowered loads in an island without a slack source."""
    shed_mw = 0.0
    affected_buses = []
    for idx in net.load.index:
        bus = int(net.load.at[idx, "bus"])
        if net.load.at[idx, "in_service"] and bus in island:
            shed_mw += float(net.load.at[idx, "p_mw"])
            net.load.at[idx, "in_service"] = False
            affected_buses.append(bus)

    for idx in net.sgen.index:
        if net.sgen.at[idx, "in_service"] and int(net.sgen.at[idx, "bus"]) in island:
            net.sgen.at[idx, "in_service"] = False

    return shed_mw, affected_buses
