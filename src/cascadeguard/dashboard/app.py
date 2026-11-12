# OWNER: P5 | NEEDS: P1,P2,P3,P4 | STATUS: ACTIVE
"""Local CascadeGuard operator console.

Run from the repository root with ``PYTHONPATH=src streamlit run src/cascadeguard/dashboard/app.py``.
The Simulation Control Center and Manager Dashboard use separate page-level controls and share
only local scenario results through the Streamlit session state.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from cascadeguard.dashboard import experience
from cascadeguard.dashboard.views import resilience, results, theft
from cascadeguard.mitigation import ADVISORY


def _theme() -> None:
    st.markdown("""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
      
      :root {
        color-scheme: dark;
        --bg-main: #060b13;
        --bg-sidebar: #080f1a;
        --card-bg: linear-gradient(145deg, #0d1726, #121f33);
        --accent-cyan: #38bdf8;
        --accent-indigo: #6366f1;
        --accent-emerald: #10b981;
      }
      
      .stApp {
        background: radial-gradient(ellipse at 50% 0%, #0d1e38 0%, #060b13 65%, #03060a 100%);
        color: #e2e8f0;
        font-family: 'Plus Jakarta Sans', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
      }
      
      h1, h2, h3, h4 {
        font-family: 'Plus Jakarta Sans', 'Segoe UI', sans-serif !important;
        letter-spacing: -0.03em;
        font-weight: 700;
      }
      
      /* Sidebar */
      [data-testid="stSidebar"] {
        background: #080f1b !important;
        border-right: 1px solid rgba(56, 189, 248, 0.12) !important;
      }
      
      [data-testid="stSidebar"] hr {
        border-color: rgba(148, 163, 184, 0.12) !important;
        margin: 1.2rem 0 !important;
      }

      /* Metric Cards */
      [data-testid="stMetric"] {
        background: var(--card-bg) !important;
        border: 1px solid rgba(56, 189, 248, 0.14) !important;
        padding: 0.85rem 1.1rem !important;
        border-radius: 14px !important;
        box-shadow: 0 4px 18px -4px rgba(0, 0, 0, 0.35);
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
      }
      [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        border-color: rgba(56, 189, 248, 0.35) !important;
        box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.45), 0 0 12px rgba(56, 189, 248, 0.15);
      }
      [data-testid="stMetricLabel"] {
        color: #94a3b8 !important;
        font-size: 0.76rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.06em !important;
      }
      [data-testid="stMetricValue"] {
        color: #f8fafc !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 1.35rem !important;
        font-weight: 700 !important;
      }
      [data-testid="stMetricDelta"] {
        font-size: 0.82rem !important;
        font-weight: 600 !important;
      }

      /* Expanders */
      [data-testid="stExpander"] {
        background: #0c1626 !important;
        border: 1px solid rgba(148, 163, 184, 0.14) !important;
        border-radius: 12px !important;
        margin-bottom: 0.9rem !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
      }
      [data-testid="stExpander"] details summary {
        font-weight: 600 !important;
        color: #e2e8f0 !important;
        padding: 0.7rem 1rem !important;
      }

      /* Buttons */
      div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg, #4f46e5 0%, #2563eb 100%) !important;
        border: none !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        letter-spacing: 0.02em !important;
        border-radius: 10px !important;
        padding: 0.55rem 1.1rem !important;
        box-shadow: 0 4px 14px rgba(79, 70, 229, 0.35) !important;
        transition: all 0.2s ease !important;
      }
      div[data-testid="stButton"] button[kind="primary"]:hover {
        background: linear-gradient(135deg, #4338ca 0%, #1d4ed8 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 20px rgba(79, 70, 229, 0.5) !important;
      }
      div[data-testid="stButton"] button:not([kind="primary"]) {
        background: #111e33 !important;
        border: 1px solid rgba(148, 163, 184, 0.18) !important;
        color: #e2e8f0 !important;
        border-radius: 10px !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
      }
      div[data-testid="stButton"] button:not([kind="primary"]):hover {
        background: #182844 !important;
        border-color: rgba(56, 189, 248, 0.3) !important;
        color: #f8fafc !important;
        transform: translateY(-1px) !important;
      }

      /* Form controls & Sliders */
      [data-baseweb="select"] {
        background: #0f1a2e !important;
        border-radius: 9px !important;
      }
      
      /* Plots */
      [data-testid="stPlotlyChart"] {
        border: 1px solid rgba(56, 189, 248, 0.16) !important;
        border-radius: 14px !important;
        overflow: hidden !important;
        box-shadow: 0 6px 24px -6px rgba(0, 0, 0, 0.45) !important;
      }

      /* Badges & Kickers */
      .cg-kicker {
        color: #38bdf8;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        font-size: 0.72rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .cg-ribbon {
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        background: linear-gradient(90deg, rgba(15, 26, 46, 0.85) 0%, rgba(12, 22, 38, 0.75) 100%);
        border: 1px solid rgba(56, 189, 248, 0.16);
        border-radius: 12px;
        padding: 9px 16px;
        margin-bottom: 1.2rem;
        box-shadow: 0 4px 16px -2px rgba(0, 0, 0, 0.35);
      }
      .cg-live-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #10b981;
        box-shadow: 0 0 10px #10b981, 0 0 4px #10b981;
        display: inline-block;
        animation: pulse-live 2s infinite ease-in-out;
      }
      @keyframes pulse-live {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.45; transform: scale(0.9); }
      }
      .cg-pill {
        background: rgba(56, 189, 248, 0.1);
        color: #38bdf8;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 0.73rem;
        font-weight: 600;
        border: 1px solid rgba(56, 189, 248, 0.2);
      }
    </style>
    """, unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="CascadeGuard · Grid Intelligence", page_icon="⚡", layout="wide",
                       initial_sidebar_state="expanded")
    _theme()
    with st.sidebar:
        st.markdown('<div class="cg-kicker">CascadeGuard · local operations</div>', unsafe_allow_html=True)
        st.markdown("## Sharavathi Grid")
        page = st.radio("Workspace", ["Simulation Control Center", "Manager Dashboard"],
                        format_func=lambda x: "⚡ Simulation Control Center" if x == "Simulation Control Center" else "📊 Manager Dashboard",
                        label_visibility="collapsed")
        st.divider()
        _season_labels = {"monsoon": "🌧️ Monsoon (High Hydro · 900 MW)", "post_monsoon": "🍂 Post-Monsoon (Moderate · 600 MW)", "summer": "☀️ Summer (Peak Demand · 350 MW)"}
        season = st.selectbox("Operating season", ["monsoon", "post_monsoon", "summer"], index=1,
                              format_func=lambda x: _season_labels.get(x, x.replace("_", " ").title()))
        intensity = st.slider("Hidden-load multiplier", 1.0, 5.0, 3.0, .5,
                              help="Used only when the theft-aware hidden-load estimate is enabled.")
        st.divider()
        st.caption("LOCAL MODEL · LOCAL DATA · NO CLOUD SERVICES")
        st.caption(ADVISORY)

    st.markdown("""
    <div class="cg-ribbon">
      <div style="display:flex; align-items:center; gap:12px;">
        <span class="cg-live-dot"></span>
        <span style="font-weight:700; font-size:0.86rem; color:#f8fafc; letter-spacing:0.03em;">SHARAVATHI–BENGALURU CORRIDOR</span>
        <span class="cg-pill">361 km · 400 kV DUAL CIRCUIT</span>
        <span class="cg-pill" style="color:#a78bfa; border-color:rgba(167,139,250,0.3); background:rgba(167,139,250,0.1);">DIGITAL TWIN</span>
      </div>
      <div style="display:flex; align-items:center; gap:16px; font-size:0.78rem; color:#94a3b8;">
        <span>⚡ <strong>39</strong> Buses · <strong>76</strong> Lines</span>
        <span>🌊 Linganamakki: <strong>1,035 MW</strong></span>
        <span>🔗 Nelamangala Tie: <strong>200 MW</strong></span>
        <span style="color:#10b981; font-weight:600;">● SIMULATOR READY</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if page == "Simulation Control Center":
        experience.render_simulation(season, float(intensity))
        with st.expander("🛡️ Verified Mitigation & AI Incident Brief", expanded=False):
            resilience.render("Operator", season, bool(st.session_state.get("grid_theft_aware", False)), float(intensity))
    else:
        experience.render_manager(season)
        with st.expander("🔍 Historical Theft & Loss Analytics", expanded=False):
            theft.render("Loss analyst")
        with st.expander("📊 Corridor Study Results", expanded=False):
            results.render()


main()
