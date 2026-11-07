# OWNER: P5 | NEEDS: P3,P4 | STATUS: ACTIVE
"""Grid Resilience view: corridor digital twin, contingency, prediction, verified mitigation, brief."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cascadeguard.dashboard import data
from cascadeguard.mitigation.network import Actions, Event, build_state, evaluate_outcome, post_contingency
from cascadeguard.mitigation.verifier import describe_actions, mitigate

SUBSTATIONS = {"SHARAVATHI": 0, "SHIMOGA": 110, "SIRA_KBCROSS": 215, "NELAMANGALA": 320, "PEENYA": 361}


@st.cache_resource(show_spinner="Building operating state...")
def get_state(season: str, theft_aware: bool, intensity: float):
    hidden = data.hidden_load_vector(season, intensity) if theft_aware else None
    return build_state(season, hidden, label="aware" if hidden else "scada")


@st.cache_data(show_spinner="Simulating and optimising...")
def run_case(season: str, theft_aware: bool, intensity: float, lines: tuple[int, ...], tie_loss: bool) -> dict[str, Any]:
    state = get_state(season, theft_aware, intensity)
    ev = Event(list(lines), tie_loss)
    res = mitigate(state, ev)
    rec = res["recommendation"]
    lib = data.case_library()
    similar = []
    if lib is not None:
        v = lib.embed(state, ev)
        similar = lib.query(v, 3, exclude=f"{state.season}|{state.label}|{ev.label}") if v is not None else []
    gnn = None
    try:
        from cascadeguard.theft.hidden_load import gnn_predict, snapshot_from_net
        gnn = gnn_predict(snapshot_from_net(state.net, ev.lines))
    except Exception:
        gnn = None
    return {"event": ev.as_dict(), "result": res, "actions_text": describe_actions(rec["actions"], rec, state),
            "similar": similar, "gnn": gnn, "hydro": state.hydro.as_dict(), "tie_mw": state.tie_mw,
            "hidden_mw": state.hidden_mw}


def corridor_figure(net, title: str, tripped: list[int] | None = None) -> go.Figure:
    df = data.corridor_frame(net)
    fig = go.Figure()
    tripped = set(tripped or [])
    for _, r in df.iterrows():
        for offset, line, load in ((0.12, r.line_a, r.load_a), (-0.12, r.line_b, r.load_b)):
            if line in tripped or load is None:
                color, dash, label = "#c0392b", "dot", "out of service"
            else:
                color = "#2e7d32" if load < 70 else ("#f39c12" if load < 95 else "#c0392b")
                dash, label = "solid", f"{load:.0f}%"
            fig.add_trace(go.Scatter(x=[r.km_from, r.km_to], y=[offset, offset], mode="lines",
                                     line=dict(color=color, width=6, dash=dash), showlegend=False,
                                     hovertemplate=f"Section {r.section} ({r['name']}) circuit "
                                                   f"{'A' if offset > 0 else 'B'}<br>line {line}: {label}<extra></extra>"))
    fig.add_trace(go.Scatter(x=list(SUBSTATIONS.values()), y=[0] * 5, mode="markers", text=list(SUBSTATIONS),
                             marker=dict(size=14, color="#1f3b73", symbol="square"), showlegend=False, hoverinfo="text"))
    fig.add_trace(go.Scatter(x=list(SUBSTATIONS.values()), y=[0.42] * 5, mode="text", text=list(SUBSTATIONS),
                             showlegend=False, hoverinfo="skip", textfont=dict(size=11, color="#1f3b73")))
    fig.update_layout(title=title, height=230, margin=dict(l=10, r=10, t=40, b=30), yaxis=dict(visible=False, range=[-0.6, 0.8]),
                      xaxis=dict(title="km from Sharavathi"), plot_bgcolor="white")
    return fig


def _metric_row(before: dict[str, Any], after: dict[str, Any]) -> None:
    c = st.columns(4)
    c[0].metric("Load lost, no action", f"{before['load_lost_pct']:.1f}%", help=f"{before['total_lost_mw']:.0f} MW")
    c[1].metric("Load lost, with plan", f"{after['load_lost_pct']:.1f}%",
                f"{after['load_lost_pct'] - before['load_lost_pct']:+.1f} pts", delta_color="inverse")
    c[2].metric("Actions", after["n_actions"])
    c[3].metric("Simulator verification", "PASSED" if after["verified"] else "FAILED")


def render(role: str, season: str, theft_aware: bool, intensity: float) -> None:
    st.subheader("Grid Resilience - Sharavathi to Bengaluru corridor")
    state = get_state(season, theft_aware, intensity)
    st.caption(f"Season **{season}** · hydro {state.hydro.base_mw:.0f} MW (max {state.hydro.max_mw:.0f} MW within "
               f"ramp/reservoir limits) · state-grid import {state.tie_mw:.0f} MW at NELAMANGALA · "
               + (f"**theft-aware**: {state.hidden_mw:.1f} MW suspected hidden load added" if state.hidden_mw else
                  "metered (SCADA) view"))
    st.plotly_chart(corridor_figure(state.net, "Pre-contingency line loading (both circuits per section)"),
                    width="stretch")
    st.caption("Line colours: green below 70 % · amber 70-95 % · red 95 % and above · red dotted = out of service. "
               "Hover a line for its loading.")

    with st.form("contingency"):
        c = st.columns([2, 2, 1, 1])
        section = c[0].selectbox("Trip section", list(range(38)), index=0,
                                 format_func=lambda s: f"S{s}: {data.corridor_frame(state.net).name[s]}")
        circuits = c[1].selectbox("Circuits", ["A", "B", "A + B (N-2)", "none"], index=0)
        tie_loss = c[2].checkbox("Lose state-grid tie")
        go_btn = c[3].form_submit_button("Simulate")
    pair = state.net["cascade_pairs"][section]
    lines = {"A": [pair[0]], "B": [pair[1]], "A + B (N-2)": list(pair), "none": []}[circuits]
    if not go_btn and "last_case" not in st.session_state:
        st.info("Choose a contingency and press **Simulate**. Example: post-monsoon, section 0, circuit A.")
        return
    if go_btn:
        if not lines and not tie_loss:
            st.warning("Select at least one line or the tie loss.")
            return
        st.session_state["last_case"] = (tuple(lines), tie_loss)
    # Re-run the chosen event under the current season / theft-aware settings.
    case = run_case(season, theft_aware, intensity, *st.session_state["last_case"])
    res = case["result"]
    before, rec = res["before"], res["recommendation"]
    st.markdown(f"#### Event: {case['event']['label']}")
    _metric_row(before, rec)

    left, right = st.columns([3, 2])
    with left:
        post, _ = post_contingency(state, Event(case["event"]["lines"], case["event"]["tie_loss"]))
        st.plotly_chart(corridor_figure(post, "Immediately after the event (before relays act)", case["event"]["lines"]),
                        width="stretch")
        st.markdown(f"**Recommendation** - stage `{res['stage']}`, {'verified' if rec['verified'] else 'NOT verified'} "
                    "by AC re-simulation:")
        for line in case["actions_text"]:
            st.markdown(f"- {line}")
        apply = st.toggle("Apply plan (simulated)", value=True)
        if apply and rec["n_actions"]:
            after_net, _ = post_contingency(state, Event(case["event"]["lines"], case["event"]["tie_loss"]),
                                            Actions.from_dict(rec["actions"]))
            st.plotly_chart(corridor_figure(after_net, "After applying the plan", case["event"]["lines"]),
                            width="stretch")
    with right:
        st.markdown("**Prediction**")
        st.write(f"P1 simulator, no action: {'cascade' if before['cascade'] else 'no further trips'}, "
                 f"{before['total_lost_mw']:.0f} MW lost"
                 + (f" (incl. {before['ufls_mw']:.0f} MW automatic UFLS)" if before["ufls_mw"] else ""))
        if case["gnn"]:
            st.write(f"Cascade GNN: cascade probability {case['gnn']['has_cascade_prob']:.2f}, "
                     f"load loss {case['gnn']['load_lost_mw']:.0f} MW")
            st.caption(f"GNN checkpoint: {case['gnn'].get('checkpoint')}. A fast estimate; the simulator result is authoritative.")
            top = case["gnn"].get("top_line_failure_probs") or []
            if top:
                names = state.net.line.name
                st.dataframe(pd.DataFrame([{"line": str(names.loc[x["line"]]),
                                            "GNN failure probability": round(x["prob"], 3)} for x in top]),
                             hide_index=True, width="stretch")
        st.markdown("**Critical lines right after the event** (AC power flow)")
        if before.get("critical_lines"):
            st.dataframe(pd.DataFrame([{"line": c["name"], "loading %": round(c["loading_pct"], 1)}
                                       for c in before["critical_lines"]]), hide_index=True, width="stretch")
        st.markdown("**Cascade path, no action** (P1 simulator)")
        seq = before.get("trip_sequence") or []
        if seq:
            st.dataframe(pd.DataFrame([{"step": s["iteration"], "line": s["name"], "cause": s["reason"],
                                        "loading %": None if s["loading_pct"] is None else round(s["loading_pct"], 1)}
                                       for s in seq]), hide_index=True, width="stretch")
        else:
            st.caption("No line trips (generation-deficit event).")
        st.markdown("**Similar past cases** (case-based retrieval)")
        if case["similar"]:
            st.dataframe(pd.DataFrame([{"case": s["case_id"], "similarity": round(s["similarity"], 3),
                                        "action type": s["signature"], "loss before %": round(s["before_lost_pct"], 1),
                                        "loss after %": round(s["after_lost_pct"], 1)} for s in case["similar"]]),
                         hide_index=True, width="stretch")
        else:
            st.caption("No case library yet - run `python -m cascadeguard.mitigation.experiment`.")
        if role != "Loss analyst":
            with st.expander("Incident brief (copilot, cited, explanation only)", expanded=role == "Operator"):
                from cascadeguard.copilot.brief import build_facts, generate_brief
                facts = build_facts(case["event"], season, before, rec, res["stage"], case["actions_text"],
                                    case["hydro"], case["similar"],
                                    {"theft_aware": bool(case["hidden_mw"]), "hidden_load_mw": round(case["hidden_mw"], 1)}
                                    if case["hidden_mw"] else None)
                brief = generate_brief(facts)
                st.caption(f"mode: {brief['mode']}" + (f" · warnings: {'; '.join(brief['warnings'])}" if brief["warnings"] else ""))
                st.markdown(brief["brief"].replace("\n", "  \n"))
                for cit in brief["citations"]:
                    if cit["cited"]:
                        st.caption(f"[{cit['n']}] {cit['title']} - {cit['section']} ({cit['status']})")

    if role == "Planner":
        st.markdown("#### Planning view - contingency study results")
        df = data.read_parquet(data.MITIGATION_DIR / "mitigation_results.parquet")
        if df is None:
            st.caption("Run the mitigation experiment to populate the study table.")
        else:
            in_season = df[df.season == season]
            sub = in_season[in_season.needs_mitigation.astype(bool)]
            st.write(f"{len(sub)} of {len(in_season)} studied events in {season} lose load without remedial action.")
            cols = [c for c in ("event", "before_lost_pct", "greedy_lost_pct", "opt_lost_pct", "opt_actions", "signature", "opt_stage")
                    if c in sub.columns]
            st.dataframe(sub[cols].sort_values("before_lost_pct", ascending=False).head(25), hide_index=True,
                         width="stretch")
