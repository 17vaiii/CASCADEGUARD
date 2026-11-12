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
      :root { color-scheme: dark; }
      .stApp { background: #080e18; color: #e2e8f0; font-family: 'Segoe UI', Arial, sans-serif; }
      h1,h2,h3,h4 { font-family: 'Segoe UI', Arial, sans-serif !important; letter-spacing: -.025em; }
      [data-testid="stSidebar"] { background: #0c1421; border-right: 1px solid #1e293b; }
      [data-testid="stMetric"] { background: #101b2b; border: 1px solid #1f2d40; padding: .72rem .9rem; border-radius: 12px; }
      [data-testid="stMetricLabel"] { color: #94a3b8; }
      [data-testid="stMetricValue"] { color: #f8fafc; font-size: 1.28rem; }
      [data-testid="stExpander"] { background: #0d1726; border: 1px solid #1e293b; border-radius: 12px; }
      div[data-testid="stButton"] button[kind="primary"] { background: #4f46e5; border: 0; }
      div[data-testid="stButton"] button { border-radius: 9px; }
      .cg-kicker { color: #7dd3fc; text-transform: uppercase; letter-spacing: .17em; font-size: .72rem; font-weight: 700; }
      .cg-subtle { color: #94a3b8; font-size: .9rem; }
      [data-testid="stPlotlyChart"] { border: 1px solid #1e293b; border-radius: 14px; overflow: hidden; }
    </style>
    """, unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="CascadeGuard · Grid Intelligence", page_icon="⚡", layout="wide",
                       initial_sidebar_state="expanded")
    _theme()
    with st.sidebar:
        st.markdown('<div class="cg-kicker">CascadeGuard · local operations</div>', unsafe_allow_html=True)
        st.markdown("## Sharavathi Grid")
        page = st.radio("Workspace", ["Simulation Control Center", "Manager Dashboard"], label_visibility="collapsed")
        st.divider()
        season = st.selectbox("Operating season", ["monsoon", "post_monsoon", "summer"], index=1,
                              format_func=lambda x: x.replace("_", " ").title())
        intensity = st.slider("Hidden-load multiplier", 1.0, 5.0, 3.0, .5,
                              help="Used only when the existing P4 hidden-load estimate is enabled.")
        st.divider()
        st.caption("LOCAL MODEL · LOCAL DATA · NO CLOUD SERVICES")
        st.caption(ADVISORY)
    if page == "Simulation Control Center":
        experience.render_simulation(season, float(intensity))
        with st.expander("Existing verified mitigation and incident brief", expanded=False):
            resilience.render("Operator", season, bool(st.session_state.get("grid_theft_aware", False)), float(intensity))
    else:
        experience.render_manager(season)
        with st.expander("Historical theft analytics", expanded=False):
            theft.render("Loss analyst")
        with st.expander("Study results", expanded=False):
            results.render()


main()
