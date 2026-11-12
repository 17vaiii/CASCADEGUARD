"""Map-first Simulation Control Center and Manager Dashboard."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cascadeguard.dashboard import data
from cascadeguard.mitigation.network import Event, build_state

SUBSTATIONS = {"SHARAVATHI": 0, "SHIMOGA": 110, "SIRA_KBCROSS": 215, "NELAMANGALA": 320, "PEENYA": 361}
# Town/site coordinates used to place the configured corridor on a geographic basemap.
CORRIDOR_COORDS = {
    "SHARAVATHI": (14.1704, 74.8388),
    "SHIMOGA": (13.9299, 75.5681),
    "SIRA_KBCROSS": (13.7412, 76.9049),
    "NELAMANGALA": (13.0983, 77.3939),
    "PEENYA": (13.0213, 77.5283),
}
THEFT_TYPES = {
    "Meter bypass": "meter_bypass", "Meter stop": "meter_stop", "Night-time tapping": "night_tapping",
    "Direct hooking": "hooking", "Temporary tampering": "temporary_tampering",
}


@st.cache_resource(show_spinner="Loading local corridor state…")
def operating_state(season: str, theft_aware: bool = False, intensity: float = 1.0):
    hidden = data.hidden_load_vector(season, intensity) if theft_aware else None
    return build_state(season, hidden, label="aware" if hidden else "scada")


def _line_name(net, idx: int) -> str:
    return str(net.line.at[int(idx), "name"])


def _corridor_coords(km: float) -> tuple[float, float]:
    anchors = list(SUBSTATIONS.items())
    for (left_name, left_km), (right_name, right_km) in zip(anchors, anchors[1:]):
        if km <= right_km:
            fraction = (km - left_km) / (right_km - left_km)
            left = CORRIDOR_COORDS[left_name]
            right = CORRIDOR_COORDS[right_name]
            return (left[0] + fraction * (right[0] - left[0]),
                    left[1] + fraction * (right[1] - left[1]))
    return CORRIDOR_COORDS[anchors[-1][0]]


def network_map(net, *, mode: str, tripped: list[int] | None = None, selected_line: int | None = None,
                feeder_rows: pd.DataFrame | None = None, selected_feeder: str | None = None,
                demo_feeder: str | None = None, loading_override: dict[int, float] | None = None,
                affected_buses: list[int] | None = None) -> go.Figure:
    """Distance schematic built only from configured corridor topology and feeder records."""
    frame = data.corridor_frame(net)
    failed = set(int(x) for x in (tripped or []))
    neighbors: set[int] = set()
    if selected_line is not None and selected_line in net.line.index:
        endpoints = {int(net.line.at[selected_line, "from_bus"]), int(net.line.at[selected_line, "to_bus"])}
        neighbors = {int(idx) for idx, line in net.line.iterrows()
                     if idx != selected_line and endpoints.intersection({int(line.from_bus), int(line.to_bus)})}
    fig = go.Figure()
    for row in frame.itertuples(index=False):
        for circuit, line_id, load, y in (("A", row.line_a, row.load_a, 1.40), ("B", row.line_b, row.load_b, 1.28)):
            line_id = int(line_id)
            is_failed = line_id in failed or not bool(net.line.at[line_id, "in_service"])
            actual_load = (loading_override or {}).get(line_id, load)
            color = "#fb7185" if is_failed else ("#f59e0b" if actual_load is not None and actual_load >= 70 else "#38bdf8")
            if line_id == selected_line:
                color = "#f8fafc"
            elif line_id in neighbors:
                color = "#34d399"
            if mode == "Loss & Theft":
                color = "#334155"
            width = 4.5 if line_id == selected_line else 2.4
            start_lat, start_lon = _corridor_coords(float(row.km_from))
            end_lat, end_lon = _corridor_coords(float(row.km_to))
            fig.add_trace(go.Scattermap(
                lat=[start_lat, end_lat], lon=[start_lon, end_lon], mode="lines",
                line={"color": color, "width": width},
                name=f"{line_id} · {circuit}", showlegend=False,
                customdata=[[line_id, "line"], [line_id, "line"]],
                hovertemplate=f"{row.name} · circuit {circuit}<br>line {line_id}<br>Loading: {actual_load if actual_load is not None else 'unavailable'}%<extra>Click line marker below to select</extra>"))
            marker_lat, marker_lon = _corridor_coords(float(row.km_from + row.km_to) / 2)
            fig.add_trace(go.Scattermap(
                lat=[marker_lat], lon=[marker_lon], mode="markers",
                marker={"size": 13 if line_id == selected_line else 9, "color": color, "opacity": .82},
                customdata=[[line_id, "line"]], name=f"Line {line_id}", showlegend=False,
                hovertemplate=f"Select {row.name} circuit {circuit}<br>Line ID {line_id}<br>Loading: {actual_load if actual_load is not None else 'unavailable'}%<extra></extra>"))

    affected = set(int(x) for x in (affected_buses or []))
    bus_km = net.get("bus_km", {})
    if bus_km:
        bx, by, bc, bd = [], [], [], []
        for bus, km in bus_km.items():
            lat, lon = _corridor_coords(float(km))
            bx.append(lat); by.append(lon)
            bc.append("#fb7185" if int(bus) in affected else "#64748b")
            bd.append([int(bus), "bus"])
    fig.add_trace(go.Scattermap(lat=bx, lon=by, mode="markers", marker={"size": [10 if b in affected else 5 for b in [x[0] for x in bd]],
            "color": bc}, customdata=bd, name="Buses",
            hovertemplate="Bus %{customdata[0]}<extra></extra>"))

    station_names = list(SUBSTATIONS)
    fig.add_trace(go.Scattermap(lat=[CORRIDOR_COORDS[name][0] for name in station_names],
        lon=[CORRIDOR_COORDS[name][1] for name in station_names], mode="markers+text",
        text=station_names, textposition="top center", textfont={"size": 11, "color": "#e2e8f0"},
        marker={"size": 15, "color": "#a78bfa", "symbol": "square"},
        customdata=[[name, "substation"] for name in station_names], name="Corridor substations",
        hovertemplate="%{text}<br>%{x} km from Sharavathi<extra></extra>"))

    if feeder_rows is not None and not feeder_rows.empty and mode in ("Loss & Theft", "Combined"):
        import math
        visible = feeder_rows.copy()
        if selected_feeder:
            visible = visible[visible.node_id.astype(str) == selected_feeder]
        xs, ys, texts, ids, sizes, colors = [], [], [], [], [], []
        line_lats, line_lons = [], []

        # Group visible feeders by parent substation to distribute them radially
        sub_feeders: dict[str, list] = {}
        for row in visible.itertuples(index=False):
            feeder = str(row.node_id)
            sub = next((s for s in station_names if feeder.startswith(s)), None)
            if sub is not None:
                sub_feeders.setdefault(sub, []).append(row)

        for sub, f_rows in sub_feeders.items():
            base_lat, base_lon = CORRIDOR_COORDS[sub]
            n_sub = len(f_rows)
            for k, row in enumerate(f_rows):
                feeder = str(row.node_id)
                # Radial dispersion around substation: 2 concentric tiers if >10 feeders
                angle = (2 * math.pi * k) / n_sub - math.pi / 2
                radius = 0.048 if n_sub <= 8 else (0.042 if (k % 2 == 0) else 0.075)
                f_lat = base_lat + radius * math.sin(angle)
                f_lon = base_lon + (radius / max(0.2, math.cos(math.radians(base_lat)))) * math.cos(angle)

                # Dotted/thin connector from substation to distribution feeder node
                line_lats.extend([base_lat, f_lat, None])
                line_lons.extend([base_lon, f_lon, None])

                xs.append(f_lat); ys.append(f_lon); texts.append(feeder); ids.append(feeder)
                score = float(getattr(row, "z", 0) or 0)
                sizes.append(10 + min(12, max(0, score)))
                colors.append("#fb7185" if bool(getattr(row, "flagged", False)) else "#f59e0b")

        if line_lats:
            fig.add_trace(go.Scattermap(lat=line_lats, lon=line_lons, mode="lines",
                line={"color": "rgba(148, 163, 184, 0.35)", "width": 1.2},
                name="Feeder distribution ties", showlegend=False, hoverinfo="skip"))

        if xs:
            fig.add_trace(go.Scattermap(lat=xs, lon=ys, mode="markers+text", text=texts, textposition="top center",
                textfont={"size": 9, "color": "#cbd5e1"}, marker={"size": sizes, "color": colors, "opacity": .9},
                customdata=[[fid, "feeder"] for fid in ids], name="Feeder leads",
                hovertemplate="<b>%{text}</b><br>Loss anomaly lead<br>Click to inspect details<extra></extra>"))

    if demo_feeder:
        sub = next((s for s in station_names if demo_feeder.startswith(s + "_")), None)
        if sub:
            demo_lat = CORRIDOR_COORDS[sub][0] + 0.085
            demo_lon = CORRIDOR_COORDS[sub][1]
            fig.add_trace(go.Scattermap(lat=[demo_lat], lon=[demo_lon], mode="markers+text",
                text=["SYNTHETIC · " + demo_feeder],
                textposition="top center", textfont={"size": 10, "color": "#c4b5fd"},
                marker={"size": 16, "color": "#8b5cf6", "symbol": "diamond"},
                customdata=[[demo_feeder, "feeder"]], name="Synthetic demonstration",
                hovertemplate="Synthetic injected scenario<br>%{text}<extra></extra>"))

    fig.update_layout(height=500, margin={"l": 18, "r": 18, "t": 24, "b": 24},
        paper_bgcolor="#0b1220", plot_bgcolor="#0b1220",
        font={"color": "#cbd5e1", "family": "'Plus Jakarta Sans', 'Segoe UI', sans-serif"},
        hoverlabel={"bgcolor": "#111c2e", "font": {"color": "#f8fafc"}},
        map={"style": "open-street-map", "center": {"lat": 13.55, "lon": 76.35}, "zoom": 7.1},
        legend={"orientation": "h", "y": 1.08}, dragmode="pan")
    return fig


def _capture_map(page: str, fig: go.Figure) -> None:
    event = st.plotly_chart(fig, key=f"{page}-network-map", on_select="rerun", selection_mode="points",
                            width="stretch", config={"scrollZoom": True, "displaylogo": False})
    points = event.selection.points if hasattr(event, "selection") else []
    if points:
        point = points[-1]
        custom = point.get("customdata") or []
        if len(custom) >= 2 and custom[1] == "line":
            st.session_state["selected_line"] = int(custom[0])
            st.session_state["pending_line"] = int(custom[0])
        elif len(custom) >= 2 and custom[1] == "feeder":
            st.session_state["selected_feeder"] = str(custom[0])
            substation = next((s for s in SUBSTATIONS if str(custom[0]).startswith(s + "_")), None)
            if substation:
                st.session_state["selected_substation"] = substation
        elif len(custom) >= 2 and custom[1] == "substation":
            st.session_state["selected_substation"] = str(custom[0])
        elif len(custom) >= 2 and custom[1] == "bus":
            st.session_state["selected_bus"] = int(custom[0])


def _run_cascade(season: str, lines: tuple[int, ...], depth: int, threshold: float, theft_aware: bool,
                 intensity: float, tie_loss: bool = False,
                 hidden_override: dict[str, Any] | None = None) -> dict[str, Any]:
    import copy
    from cascadeguard.data.cascade_sim.grid.cascade import simulate_cascade
    if hidden_override:
        state = build_state(season, [{"bus_id": hidden_override["substation"],
                                      "hidden_load_mw": hidden_override["hidden_mw"],
                                      "power_factor": .95, "source": "suspected_unmetered_load"}],
                            label="aware")
    else:
        state = operating_state(season, theft_aware, intensity)
    net = copy.deepcopy(state.net)
    if tie_loss:
        net.sgen.at[state.tie_idx, "p_mw"] = 0.0
        net.sgen.at[state.tie_idx, "q_mvar"] = 0.0
        net.sgen.at[state.tie_idx, "in_service"] = False
    result = simulate_cascade(net, list(lines), loading_threshold=threshold, max_iterations=depth)
    prediction = None
    try:
        from cascadeguard.theft.hidden_load import gnn_predict, snapshot_from_net
        prediction = gnn_predict(snapshot_from_net(net, list(lines)))
    except Exception:
        pass
    return {"result": result, "season": season, "lines": list(lines), "tie_loss": tie_loss,
            "state": "theft-aware" if theft_aware or hidden_override is not None else "baseline",
            "hidden_mw": state.hidden_mw, "gnn": prediction}


def _run_impact_comparison(season: str, lines: tuple[int, ...], depth: int, threshold: float,
                           intensity: float, tie_loss: bool = False,
                           theft_case: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    base = _run_cascade(season, lines, depth, threshold, False, intensity, tie_loss)
    hidden = None
    if theft_case:
        hidden_mw = max(0.0, float(theft_case["residual_mwh"]) * 1000 /
                        (float(theft_case["duration"]) * 24))
        hidden = {"substation": theft_case["substation"], "hidden_mw": hidden_mw}
    aware = _run_cascade(season, lines, depth, threshold, not bool(hidden), intensity, tie_loss, hidden)
    return base, aware


def _feeder_summary() -> pd.DataFrame | None:
    frame = data.read_parquet(data.THEFT_DIR / "feeder_balance_summary.parquet")
    return frame if frame is not None and "node_id" in frame else None


def _theft_leads_frame() -> pd.DataFrame:
    return pd.DataFrame(data.theft_leads() or [])


def _run_theft_scenario(feeder_id: str, theft_type: str, intensity: float, duration_days: int,
                        affected: int, start_day: int = 23, start_date: date | None = None) -> dict[str, Any]:
    from cascadeguard.theft import load_config
    from cascadeguard.theft.feeder_sim import simulate_distribution
    from cascadeguard.theft.energy_balance import feeder_balance, dt_balance
    from cascadeguard.theft.service import load_bundle, score_frame
    config = load_config()
    substation = next((s for s in SUBSTATIONS if feeder_id.startswith(s + "_")), None)
    if substation is None:
        raise ValueError("Select a supported corridor feeder")
    sim = config["simulation"]
    sim.update({"days": 45, "history_days": 22, "min_event_days": 7,
                "start": (start_date or date.fromisoformat(str(sim["start"])) ).isoformat(),
                "feeders_per_substation": {substation: 1}, "area_by_substation": {substation: sim["area_by_substation"][substation]},
                "dts_per_feeder": [2, 2], "consumers_per_dt": [12, 12], "theft_fraction": 0.0,
                "dt_metered_fraction": 1.0, "lookalike_fraction": 0.0, "comm_failure_fraction": 0.0,
                "new_connection_feeder_fraction": 0.0})
    ds = simulate_distribution(config, seed=177, injection={"feeder_id": feeder_id, "theft_type": theft_type,
        "intensity": intensity, "duration_days": duration_days, "affected_consumers": affected,
        "start_idx": int(start_day * 24), "substation": substation})
    balance = feeder_balance(ds, config["energy_balance"]["flag_z"])
    dt_result = dt_balance(ds, config["energy_balance"]["flag_z"])
    frame = ds.to_meter_frame()
    scored = score_frame(frame, ds.timestamps[ds.history_end], load_bundle(), ds.tamper_log,
                         balance.summary, dt_result.summary)
    summary = balance.summary.set_index("node_id").loc[feeder_id]
    index = ds.feeders.index[ds.feeders.feeder_id == feeder_id][0]
    slot = slice(ds.history_end, None)
    injected = ds.consumers[ds.consumers.feeder_id == feeder_id]
    from cascadeguard.api.audit import create_recommendation
    audit = create_recommendation(
        {"kind": "synthetic_theft_demonstration", "feeder_id": feeder_id, "theft_type": theft_type,
         "synthetic_ground_truth": True,
         "leads": [{"consumer_ref": lead["consumer_ref"], "score": lead["score"], "confidence": lead["confidence"]}
                   for lead in scored["leads"]]},
        [feeder_id, "local_p4_theft_demo"])
    return {"feeder": feeder_id, "substation": substation, "type": theft_type, "intensity": intensity,
        "duration": duration_days, "affected": int(injected.is_theft.sum()), "summary": summary.to_dict(),
        "input_mwh": float(ds.feeder_input_kwh[index, slot].sum() / 1000),
        "metered_mwh": float(balance.metered_kwh[index, slot].sum() / 1000),
        "technical_mwh": float(balance.tech_loss_kwh[index, slot].sum() / 1000),
        "residual_mwh": float(summary["excess_residual_kwh"] / 1000), "scored": scored,
        "actual_truth_count": int(injected.is_theft.sum()), "disclaimer": scored["disclaimer"],
        "start_timestamp": ds.timestamps[int(injected.event_start.iloc[0])].isoformat(), "audit_id": audit["audit_id"]}


def _map_result(page: str, state, mode: str, current: dict[str, Any] | None, feeders: pd.DataFrame | None):
    trips = current["result"].failed_lines if current else []
    seq = current["result"].line_trip_sequence if current else []
    event_idx = st.session_state.get("timeline_event")
    if seq and event_idx is not None and 0 <= int(event_idx) < len(seq):
        trips = [int(x["line_idx"]) for x in seq[:int(event_idx) + 1]]
    selected = st.session_state.get("selected_line")
    demo = st.session_state.get("shared_theft_result")
    res = current["result"] if current else None
    _capture_map(page, network_map(state.net, mode=mode, tripped=trips, selected_line=selected,
                                  feeder_rows=feeders, selected_feeder=st.session_state.get("selected_feeder"),
                                  demo_feeder=demo.get("feeder") if demo else None,
                                  loading_override=res.final_line_loading if res else None,
                                  affected_buses=res.affected_buses if res else None))


def _top_status(state, feeder_summary: pd.DataFrame | None):
    suspicious = int(feeder_summary.flagged.sum()) if feeder_summary is not None and "flagged" in feeder_summary else 0
    c = st.columns([1.2, 1.2, 1.2, 1.3, 2.8])
    c[0].metric("Corridor", "LOCAL · LIVE MODEL")
    c[1].metric("Grid condition", "Monitored")
    c[2].metric("Suspicious feeders", suspicious)
    c[3].metric("Substations", len(SUBSTATIONS))
    c[4].caption("Sharavathi → Shimoga → Sira/KC Cross → Nelamangala → Peenya · topology shown by configured route distance")


def _configure_right(page: str, season: str, state, theft_aware: bool, intensity: float) -> dict[str, Any] | None:
    with st.expander("Selected element", expanded=True):
        line_id = st.session_state.get("selected_line")
        feeder = st.session_state.get("selected_feeder")
        if line_id is not None:
            st.markdown(f"**Transmission line {line_id}**")
            st.caption(_line_name(state.net, line_id))
            st.write(f"Section {state.net['line_section'][line_id]} · circuit {state.net['line_circuit'][line_id]} · "
                     f"{'in service' if state.net.line.at[line_id, 'in_service'] else 'out of service'}")
        elif feeder:
            st.markdown(f"**Feeder {feeder}**")
            st.caption("Selected from existing feeder loss leads; scores are inspection leads, not confirmed theft.")
        elif st.session_state.get("selected_bus") is not None:
            bus = st.session_state["selected_bus"]
            st.markdown(f"**Network bus {bus}**")
            st.caption(f"Configured corridor position: {state.net['bus_km'].get(bus, 'unknown')} km")
        elif st.session_state.get("selected_substation"):
            sub = st.session_state["selected_substation"]
            st.markdown(f"**{sub} substation**")
            st.caption(f"Configured corridor position: {SUBSTATIONS[sub]} km from Sharavathi")
        else:
            st.caption("Select a line marker or feeder marker on the map to inspect it.")
        key = f"{page}-initial-trips"
        pending = st.session_state.pop("pending_line", None)
        if pending is not None:
            current = list(st.session_state.get(key, []))
            if pending not in current:
                current.append(pending)
            st.session_state[key] = current
        if key in st.session_state:
            chosen = st.multiselect("Initial line trips (N-k)", options=list(state.net.line.index),
                format_func=lambda x: f"{x} · {_line_name(state.net, x)}", key=key)
        else:
            chosen = st.multiselect("Initial line trips (N-k)", options=list(state.net.line.index),
                default=([line_id] if line_id is not None and line_id in state.net.line.index else []),
                format_func=lambda x: f"{x} · {_line_name(state.net, x)}", key=key)
        return {"lines": tuple(int(x) for x in chosen)}


def _scenario_controls(season: str, intensity: float, lines: tuple[int, ...], page: str):
    with st.expander("⚙️ Simulation Settings", expanded=False):
        threshold = st.slider("Overload trip threshold (%)", 80, 150, 100, 5, key=f"{page}-threshold")
        depth = st.slider("Maximum cascade depth", 1, 20, 10, key=f"{page}-depth")
        tie = st.checkbox("Disable state-grid tie", key=f"{page}-tie-loss")
        if st.button("Run grid simulation", type="primary", width="stretch", key=f"{page}-run-grid"):
            if not lines and not tie:
                st.info("No transmission lines selected. Select a line on the network map, or disable the state-grid tie to run this scenario.")
            else:
                try:
                    st.session_state["shared_grid_result"] = _run_cascade(season, lines, depth, threshold,
                        st.session_state.get("grid_theft_aware", False), intensity, tie)
                    st.session_state["grid_run_config"] = {"season": season, "lines": lines, "depth": depth, "threshold": threshold, "tie_loss": tie}
                    st.session_state["timeline_event"] = 0
                except Exception as exc:
                    st.error(f"Simulation could not run: {exc}")
        if st.button("Reset scenario", width="stretch", key=f"{page}-reset"):
            st.session_state.pop("shared_grid_result", None)
            st.session_state.pop("impact_comparison", None)
            st.session_state.pop("shared_theft_result", None)
            st.session_state.pop("timeline_event", None)
            st.session_state["pending_clear_scenario"] = True
            st.rerun()
        saved = st.session_state.get("saved_scenario")
        if st.button("Save current configuration", width="stretch", key=f"{page}-save"):
            st.session_state["saved_scenario"] = {"season": season, "lines": list(lines), "depth": depth, "threshold": threshold}
            st.success("Configuration saved for this local session.")
        if saved and st.button("Load saved configuration", width="stretch", key=f"{page}-load"):
            st.session_state["pending_saved_scenario"] = saved
            st.rerun()
        if st.button("Run Before vs After Theft Impact", width="stretch", key=f"{page}-impact"):
            if not lines:
                st.warning("Select the contingency lines first so both runs use the same event.")
            elif st.session_state.get("shared_theft_result") is None and data.read_parquet(
                    data.THEFT_DIR / "ntl_ratio_by_substation.parquet") is None:
                st.error("The existing P4 hidden-load artifact is missing; run the local theft pipeline first.")
            else:
                try:
                    theft_case = st.session_state.get("shared_theft_result")
                    st.session_state["impact_comparison"] = _run_impact_comparison(season, lines, depth, threshold,
                        intensity, tie, theft_case)
                except Exception as exc:
                    st.error(f"Impact comparison could not run: {exc}")
        if st.button("Step forward", width="stretch", key=f"{page}-step"):
            sequence = (st.session_state.get("shared_grid_result") or {}).get("result")
            events = sequence.line_trip_sequence if sequence else []
            current = int(st.session_state.get("timeline_event", -1))
            st.session_state["timeline_event"] = min(current + 1, len(events) - 1) if events else -1
    return st.session_state.get("shared_grid_result")


def _render_result(result: dict[str, Any] | None, state, season: str, lines: tuple[int, ...], depth: int, threshold: float,
                   theft_aware: bool, intensity: float):
    if result:
        sim = result["result"]
        st.markdown("#### 📊 Latest Simulation Run")
        cols = st.columns(4)
        cols[0].metric("Actual lines tripped", sim.total_lines_tripped)
        cols[1].metric("Load lost", f"{sim.load_lost_mw:,.1f} MW", f"{sim.load_shed_pct:.1f}%")
        cols[2].metric("Cascade depth", sim.cascade_depth)
        cols[3].metric("Affected buses", len(sim.affected_buses))
        st.caption(f"AC cascade simulator · {result['state'].title()} grid state · converged: {sim.converged} · initial lines: {result['lines']} · tie loss: {result.get('tie_loss', False)}")
        if result.get("gnn"):
            gnn = result["gnn"]
            st.info(f"⚡ Cascade GNN prediction: probability **{gnn.get('has_cascade_prob', float('nan')):.2f}** | "
                    f"predicted load loss **{gnn.get('load_lost_mw', float('nan')):.1f} MW** (Rapid surrogate screening estimate)")
        else:
            st.caption("Cascade GNN checkpoint unavailable; simulator results remain available.")
    impact = st.session_state.get("impact_comparison")
    if impact:
        base, aware = impact
        a, b = base["result"], aware["result"]
        st.markdown("#### ⚖️ Clean vs Theft-Aware Impact Comparison")
        c = st.columns(4)
        c[0].metric("Baseline trips", a.total_lines_tripped)
        c[1].metric("Theft-aware trips", b.total_lines_tripped, b.total_lines_tripped - a.total_lines_tripped)
        c[2].metric("Baseline load lost", f"{a.load_lost_mw:.1f} MW")
        c[3].metric("Theft-aware load lost", f"{b.load_lost_mw:.1f} MW", f"{b.load_lost_mw-a.load_lost_mw:+.1f} MW")
        if base.get("gnn") and aware.get("gnn"):
            x, y = st.columns(2)
            x.metric("Baseline GNN cascade probability", f"{base['gnn'].get('has_cascade_prob', float('nan')):.2f}")
            y.metric("Theft-aware GNN cascade probability", f"{aware['gnn'].get('has_cascade_prob', float('nan')):.2f}",
                     f"{aware['gnn'].get('has_cascade_prob', 0)-base['gnn'].get('has_cascade_prob', 0):+.2f}")
        view = st.radio("Comparison view", ["Switch map layer", "Side-by-side maps"], horizontal=True, key="impact-layer")
        if view == "Side-by-side maps":
            left, right = st.columns(2)
            for col, item, label in ((left, base, "Baseline · no suspected hidden load"),
                                     (right, aware, "Theft-aware · hidden load added")):
                with col:
                    st.caption(label)
                    st.plotly_chart(network_map(state.net, mode="Grid resilience", tripped=item["result"].failed_lines,
                        loading_override=item["result"].final_line_loading, affected_buses=item["result"].affected_buses),
                        key=f"impact-map-{item['state']}", width="stretch")
        else:
            which = st.radio("Displayed scenario", ["Baseline", "Theft-aware"], horizontal=True, key="impact-layer-choice")
            item = base if which == "Baseline" else aware
            st.plotly_chart(network_map(state.net, mode="Grid resilience", tripped=item["result"].failed_lines,
                loading_override=item["result"].final_line_loading, affected_buses=item["result"].affected_buses),
                key=f"impact-map-{which}", width="stretch")
        st.caption("Both evaluations execute identical contingencies under matched seasonal parameters.")
        st.caption(f"Estimated hidden load applied in theft-aware state: {aware['hidden_mw']:.3f} MW. "
                   + ("Derived from active synthetic feeder energy-balance calculation." if st.session_state.get("shared_theft_result") else "Derived from pre-computed distribution substation residual model."))


def _theft_injection_panel(advanced: bool = True):
    with st.expander("🔬 Synthetic Theft Injection & Detection Lab", expanded=False):
        cols = st.columns(2)
        stations = list(SUBSTATIONS)
        preferred_sub = st.session_state.get("selected_substation")
        current_sub = st.session_state.get("demo-substation", preferred_sub if preferred_sub in stations else "NELAMANGALA")
        sub = cols[0].selectbox("Corridor substation", stations, index=stations.index(current_sub), key="demo-substation")
        summary = _feeder_summary()
        feeder_choices = summary.loc[summary.node_id.astype(str).str.startswith(sub + "_"), "node_id"].astype(str).tolist() if summary is not None else []
        if not feeder_choices:
            feeder_choices = [f"{sub}_F00"]
        selected_feed = st.session_state.get("selected_feeder")
        current_feed = st.session_state.get("demo-feeder")
        if selected_feed and selected_feed.startswith(sub + "_"):
            current_feed = selected_feed
        if current_feed not in feeder_choices:
            current_feed = feeder_choices[0]
        feeder_id = cols[1].selectbox("Feeder", feeder_choices, index=feeder_choices.index(current_feed), key="demo-feeder")
        theft_type = THEFT_TYPES[st.selectbox("Theft pattern", list(THEFT_TYPES), key="demo-theft-type")]
        if advanced:
            c = st.columns(4)
            intensity = c[0].slider("Intensity", 0.5, 2.0, 1.0, 0.1, key="demo-theft-intensity")
            duration = c[1].slider("Duration (days)", 7, 20, 10, key="demo-theft-duration")
            affected = c[2].slider("Affected consumers", 1, 8, 3, key="demo-theft-affected")
            start_day = c[3].slider("Start day in generated run", 23, 25, 23, key="demo-theft-start-day")
            from cascadeguard.theft import load_config
            configured_start = date.fromisoformat(str(load_config()["simulation"]["start"]))
            start_date = st.date_input("Generated timeline start date", value=configured_start, key="demo-theft-date")
        else:
            intensity, duration, affected, start_day = 1.0, 10, 3, 23
            from cascadeguard.theft import load_config
            start_date = date.fromisoformat(str(load_config()["simulation"]["start"]))
            st.caption("The demonstration uses the standard local scenario settings; advanced controls are in Simulation Control Center.")
        st.caption(f"Synthetic feeder {feeder_id} · theft begins on generated day {start_day}; the P4 minimum event duration is 7 days.")
        if st.button("Inject and run theft detection", type="primary", key="inject-theft", width="stretch"):
            try:
                with st.spinner("Running the local distribution simulator, energy balance and trained theft scoring bundle…"):
                    st.session_state["shared_theft_result"] = _run_theft_scenario(
                        feeder_id, theft_type, intensity, duration, affected, start_day, start_date)
                    st.session_state["theft_just_injected"] = True
                    st.rerun()
            except Exception as exc:
                st.error(f"The local theft workflow could not run: {exc}")
    result = st.session_state.get("shared_theft_result")
    if result:
        if st.session_state.pop("theft_just_injected", False):
            st.success(f"✅ Injection succeeded for feeder **{result['feeder']}**! The scenario marker is now active on the corridor map.")
        st.markdown(f"### 🔬 Injected Scenario: `{result['feeder']}` · {result['type'].replace('_', ' ').title()}")
        st.caption(f"Substation: **{result['substation']}** · Injected duration: **{result['duration']} days** · Affected consumers: **{result['affected']}**")
        metrics = (
            ("Feeder input", f"{result['input_mwh']:.2f} MWh", {}),
            ("Metered consumption", f"{result['metered_mwh']:.2f} MWh", {}),
            ("Technical loss", f"{result['technical_mwh']:.2f} MWh", {}),
            ("Unexplained residual", f"{result['residual_mwh']:.2f} MWh",
             {"delta": "Suspected hidden load", "delta_color": "inverse"}),
        )
        for col, (label, value, options) in zip(st.columns(4), metrics):
            with col.container(border=True):
                st.metric(label, value, **options)
        summary = result["summary"]
        st.info(f"📊 Distribution Anomaly Z-Score: **{summary['z']:.2f}** · Detection Time: `{result['start_timestamp']}` · Audit ID: `{result['audit_id'][:12]}`")
        scored = result["scored"]
        if scored["leads"]:
            st.markdown("**Top Suspected Consumer Meters Ranked by Model Anomaly Score:**")
            table = pd.DataFrame([{"rank": x["rank"], "consumer": x["consumer_ref"], "feeder": x["feeder_id"],
                                   "score": round(x["score"], 3), "confidence": x["confidence"], "reasons": ", ".join(r["code"] for r in x["reason_codes"])}
                                  for x in scored["leads"][:10]])
            st.dataframe(table, hide_index=True, width="stretch")
            st.success(f"**Lead Assessment:** {scored['leads'][0]['summary']}")
        st.caption("Distribution anomaly scores evaluate consumer smart-meter patterns; this injection is synthetic ground truth for operational demonstration.")


def render_simulation(season: str, intensity: float):
    if st.session_state.pop("pending_clear_scenario", False):
        st.session_state["simulation-initial-trips"] = []
        st.session_state["timeline_event"] = 0
        st.session_state.pop("selected_line", None)
    saved = st.session_state.pop("pending_saved_scenario", None)
    if saved:
        st.session_state["simulation-initial-trips"] = saved["lines"]
        st.session_state["simulation-depth"] = saved["depth"]
        st.session_state["simulation-threshold"] = saved["threshold"]
    st.markdown("## ⚡ Grid Simulation")
    st.info("Select transmission lines on the map, configure a failure scenario, and run the cascade simulator to see how faults propagate.")
    theft_aware = st.toggle("🔓 Enable Theft-Aware Mode", value=False, key="grid_theft_aware",
                            help="Adds estimated hidden load from theft detection to the grid state")
    state = operating_state(season, theft_aware, intensity)
    feeders = _feeder_summary()
    status = st.columns([1, 1, 1, 2])
    status[0].metric("Season", season.replace("_", " ").title())
    status[1].metric("Hydro dispatch", f"{state.hydro.base_mw:.0f} MW")
    status[2].metric("State-grid import", f"{state.tie_mw:.0f} MW")
    status[3].caption(f"{'Theft-aware' if state.hidden_mw else 'Baseline'} · estimated hidden load {state.hidden_mw:.1f} MW")
    _theft_injection_panel()
    map_col, panel_col = st.columns([4.3, 1.35], gap="medium")
    with map_col:
        map_mode = st.radio("Network layer", ["Grid resilience", "Loss & Theft", "Combined"],
                            index=1, horizontal=True, key="simulation-map-mode")
        st.markdown("### Corridor network · select a circuit marker")
        result = st.session_state.get("shared_grid_result")
        _map_result("simulation", state, map_mode, result, feeders)
        st.markdown(
            '<div style="font-size:0.78rem;color:#94a3b8;display:flex;gap:14px;flex-wrap:wrap;margin-top:4px;">'
            '<span><span style="color:#22c55e;">●</span> Normal</span>'
            '<span><span style="color:#f59e0b;">●</span> High load</span>'
            '<span><span style="color:#fb7185;">◌</span> Tripped / red</span>'
            '<span><span style="color:#a78bfa;">■</span> Substation</span>'
            '<span><span style="color:#f59e0b;">●</span> Feeder lead</span>'
            '</div>', unsafe_allow_html=True)
    with panel_col:
        selection = _configure_right("simulation", season, state, theft_aware, intensity)
        result = _scenario_controls(season, intensity, selection["lines"], "simulation")
    config = st.session_state.get("grid_run_config", {})
    _render_result(result, state, season, selection["lines"], config.get("depth", 10), config.get("threshold", 100), theft_aware, intensity)
    with st.expander("📋 Cascade Event Sequence (Relay Trips)", expanded=bool(result)):
        sequence = result["result"].line_trip_sequence if result else []
        if sequence:
            table = pd.DataFrame(sequence)
            st.dataframe(table, hide_index=True, width="stretch")
            idx = st.slider("Highlight event step", 0, len(sequence) - 1, min(int(st.session_state.get("timeline_event", 0)), len(sequence)-1), key="timeline-step-slider")
            st.session_state["timeline_event"] = idx
            step = sequence[idx]
            st.session_state["selected_line"] = int(step["line_idx"])
            st.info(f"Step {step['iteration']} · line {step['line_idx']} {step['name']} · {step['reason']} · loading {step.get('loading_pct') or 'not applicable'}")
        else:
            st.caption("Run a grid simulation above to populate the chronological trip sequence.")


def render_manager(season: str):
    st.markdown("## Manager Dashboard")
    st.caption("Executive overview of transmission corridor reliability, distribution feeder anomaly screening, and inspection dispatch.")
    state = operating_state(season, False, 1.0)
    feeders = _feeder_summary()
    leads = _theft_leads_frame()
    total_suspicious = int(feeders.flagged.sum()) if feeders is not None and "flagged" in feeders else 0
    incidents = st.session_state.get("shared_theft_result")
    top = st.columns([1.2, 1.2, 1.2, 1.2, 1.2, 2.2])
    top[0].metric("Grid state", "Monitored")
    top[1].metric("Active simulated failures", (st.session_state.get("shared_grid_result") or {}).get("result").total_lines_tripped if st.session_state.get("shared_grid_result") else 0)
    top[2].metric("Suspicious feeders", total_suspicious)
    top[3].metric("Ranked leads", len(leads))
    top[4].metric("Demo scenarios", int(bool(incidents)))
    top[5].caption("Local-only monitoring · model outputs update from the shared session state")
    mode = st.radio("Map layer", ["Grid resilience", "Loss & Theft", "Combined"], horizontal=True, key="manager-map-mode")
    filtered = feeders
    if feeders is not None and mode == "Loss & Theft":
        filtered = feeders.sort_values("z", ascending=False).head(12) if "z" in feeders else feeders.head(12)
    map_col, side_col = st.columns([4.3, 1.35], gap="medium")
    with map_col:
        st.markdown("### Sharavathi–Bengaluru network")
        result = st.session_state.get("shared_grid_result")
        _map_result("manager", state, mode, result, filtered)
        st.caption("The corridor uses configured distance coordinates. Feeder leads are shown at their configured parent substation as diagrammatic markers.")
    with side_col:
        with st.expander("📍 Location Details & Asset State", expanded=True):
            feeder = st.session_state.get("selected_feeder")
            if feeder:
                st.write(f"**{feeder}**")
                if feeders is not None and feeder in set(feeders.node_id.astype(str)):
                    row = feeders[feeders.node_id.astype(str) == feeder].iloc[0]
                    for key in ("z", "change_pct", "recent_pct", "flagged"):
                        if key in row:
                            st.write(f"{key.replace('_', ' ').title()}: {row[key]}")
                if not leads.empty and "substation" in leads:
                    st.caption("Existing consumer leads for the selected substation are listed below when available.")
            elif st.session_state.get("selected_line") is not None:
                line_id = st.session_state["selected_line"]
                st.write(f"**{_line_name(state.net, line_id)}**")
                st.caption("Transmission asset · loading and cascade risk can be inspected in the simulation view.")
            else:
                st.caption("Select a corridor line or feeder lead marker.")
            if st.session_state.get("shared_grid_result"):
                sim = st.session_state["shared_grid_result"]["result"]
                st.write(f"Actual simulator cascade: {sim.total_lines_tripped} line trips · {sim.load_lost_mw:.1f} MW load loss")
                pred = st.session_state["shared_grid_result"].get("gnn")
                if pred:
                    st.caption(f"Cascade GNN probability: {pred.get('has_cascade_prob', float('nan')):.2f} (model estimate)")
        with st.expander("🔎 Field Inspection Lead Review", expanded=False):
            search = st.text_input("Search existing leads", key="manager-incident-search")
            severity = st.selectbox("Filter by lead score", ["All", "High ≥0.7", "Medium 0.4–0.69", "Lower <0.4"], key="manager-severity")
            if not leads.empty:
                records = leads.copy()
                locations = sorted(records.substation.dropna().astype(str).unique()) if "substation" in records else []
                location = st.selectbox("Filter by location", ["All locations", *locations], key="manager-location-filter")
                if location != "All locations" and "substation" in records:
                    records = records[records.substation.astype(str) == location]
                if "score" in records:
                    if severity.startswith("High"):
                        records = records[records.score >= .7]
                    elif severity.startswith("Medium"):
                        records = records[records.score.between(.4, .69)]
                    elif severity.startswith("Lower"):
                        records = records[records.score < .4]
                if search:
                    records = records[records.astype(str).apply(lambda col: col.str.contains(search, case=False)).any(axis=1)]
                label_col = "lead_id" if "lead_id" in records else "consumer_ref"
                st.dataframe(records.head(20), hide_index=True, width="stretch", height=250)
                pick = st.selectbox("Review lead", records[label_col].astype(str).tolist() if label_col in records else [], key="manager-review-pick")
                if pick:
                    col1, col2 = st.columns(2)
                    if col1.button("✅ Acknowledge", key="manager-ack"):
                        _record_manager_review(pick, records, "acknowledged")
                    if col2.button("📝 Mark Reviewed", key="manager-reviewed"):
                        _record_manager_review(pick, records, "reviewed")
                    st.caption(st.session_state.get("reviewed_leads", {}).get(pick, "Not reviewed"))
            else:
                st.caption("P4 inspection leads are not present in this local checkout.")
    _theft_injection_panel(advanced=False)
    current = st.session_state.get("shared_theft_result")
    if current:
        st.info(f"Synthetic demonstration · {current['feeder']} · P4 score output available · {current['disclaimer']}")
        reviewed = st.session_state.get("reviewed_leads", {}).get(current["audit_id"], "Not reviewed")
        st.caption(f"Incident {current['audit_id'][:10]} · review status: {reviewed}")
        x, y = st.columns(2)
        if x.button("Acknowledge synthetic scenario", key="manager-ack-demo"):
            _record_manager_review(current["audit_id"], None, "acknowledged", synthetic=True)
        if y.button("Mark synthetic scenario reviewed", key="manager-reviewed-demo"):
            _record_manager_review(current["audit_id"], None, "reviewed", synthetic=True)
    with st.expander("📈 Feeder Anomaly Analytics", expanded=False):
        if feeders is not None and "z" in feeders:
            st.markdown("**Feeder anomaly z-score (existing energy-balance output)**")
            ordered = feeders.sort_values("z", ascending=False).head(15)
            chart = go.Figure(go.Bar(x=ordered.z, y=ordered.node_id, customdata=ordered.node_id, orientation="h",
                marker_color=["#fb7185" if bool(v) else "#f59e0b" for v in ordered.flagged]))
            chart.update_layout(height=360, paper_bgcolor="#0b1220", plot_bgcolor="#0b1220", font_color="#cbd5e1",
                margin={"l": 10, "r": 12, "t": 20, "b": 20}, xaxis_title="z-score", yaxis={"autorange": "reversed"})
            event = st.plotly_chart(chart, width="stretch", key="manager-feeder-analytics",
                                    on_select="rerun", selection_mode="points")
            points = event.selection.points if hasattr(event, "selection") else []
            if points:
                point = points[-1]
                custom = point.get("customdata")
                if custom is not None:
                    st.session_state["selected_feeder"] = str(custom)
        else:
            st.caption("No feeder summary artifact is available.")


def _record_manager_review(pick: str, records: pd.DataFrame | None, status: str, synthetic: bool = False) -> None:
    """Write a durable local review annotation without treating suspicion as confirmed theft."""
    from cascadeguard.api.audit import create_recommendation, record_verification
    audit_ids = st.session_state.setdefault("lead_audit_ids", {})
    audit_id = pick
    if not synthetic:
        audit_id = audit_ids.get(pick)
        if not audit_id:
            row = records[records.lead_id.astype(str) == pick].iloc[0] if records is not None and "lead_id" in records else {}
            audit = create_recommendation({"kind": "manager_review_of_existing_theft_lead", "lead_id": pick,
                "score": row.get("score") if hasattr(row, "get") else None,
                "confidence": row.get("confidence") if hasattr(row, "get") else None}, [pick, "existing_p4_artifact"])
            audit_id = audit["audit_id"]
            audit_ids[pick] = audit_id
    record_verification(audit_id, {"verified": False, "outcome": "manager_review",
        "details": {"review_status": status, "theft_confirmed": False, "synthetic_demonstration": synthetic}})
    st.session_state.setdefault("reviewed_leads", {})[pick] = f"{status.title()} · audit {audit_id[:10]} · unconfirmed"

