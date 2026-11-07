# OWNER: P5 | NEEDS: P2 | STATUS: ACTIVE
"""CascadeGuard operator console (Streamlit + Plotly) - PRD P2 platform requirement, P5-6/7/10.

Run from the repository root::

    PYTHONPATH=src streamlit run src/cascadeguard/dashboard/app.py

Views: Grid Resilience (digital twin, contingency, prediction, verified mitigation, cited brief,
theft-aware toggle) and Loss & Theft (heatmap, loss split, inspection list with reasons),
plus Results. The role selector (operator / planner / loss analyst) changes the panels shown.
Advisory only: nothing here can operate equipment.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):                       # allow `streamlit run path/to/app.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from cascadeguard.dashboard.views import resilience, results, theft
from cascadeguard.mitigation import ADVISORY

ROLES = ("Operator", "Planner", "Loss analyst")


def main() -> None:
    st.set_page_config(page_title="CascadeGuard - Sharavathi corridor", layout="wide")
    st.title("CascadeGuard - Sharavathi-Bengaluru corridor")
    st.warning("Simulation-only research prototype. " + ADVISORY)
    with st.sidebar:
        role = st.radio("Role", ROLES, index=0)
        season = st.selectbox("Season", ["monsoon", "post_monsoon", "summer"], index=1)
        theft_aware = st.toggle("Theft-aware grid state (P4 hidden load)", value=False,
                                help="Adds P4's estimated unmetered load per substation to the operating state.")
        intensity = st.slider("Hidden-load intensity (x simulated NTL)", 1.0, 5.0, 3.0, 0.5, disabled=not theft_aware)
        st.caption("Corridor and all parameters are assumptions; see configs/ and docs/.")
    order = ["Loss & Theft", "Grid Resilience", "Results"] if role == "Loss analyst" else \
        ["Grid Resilience", "Loss & Theft", "Results"]
    tabs = st.tabs(order)
    for name, tab in zip(order, tabs):
        with tab:
            if name == "Grid Resilience":
                resilience.render(role, season, theft_aware, float(intensity))
            elif name == "Loss & Theft":
                theft.render(role)
            else:
                results.render()


main()
