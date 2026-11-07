# OWNER: P5 | NEEDS: P3,P4 | STATUS: ACTIVE
"""Loss & Theft view: feeder heatmap, technical vs non-technical split, ranked inspection leads."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from cascadeguard.dashboard import data
from cascadeguard.theft import hashed_id

MISSING = "P4 artifacts not found. Run `PYTHONPATH=src python -m cascadeguard.theft.pipeline` first."


def render(role: str) -> None:
    st.subheader("Loss & Theft - suspected non-technical loss (simulated data)")
    st.caption("Scores are leads for field inspection, never evidence of theft. Consumer IDs are synthetic pseudonyms.")
    metrics = data.read_json(data.THEFT_METRICS)
    if metrics is None:
        st.warning(MISSING)
        return
    split = metrics["technical_loss"]["split_recent"]
    c = st.columns(4)
    c[0].metric("Feeder input (scoring window)", f"{split['input_mwh']:,.0f} MWh")
    c[1].metric("Technical loss (estimated)", f"{split['technical_loss_pct_est']:.2f}%")
    c[1].caption(f"Simulated truth: {split['technical_loss_pct_true']:.2f}%")
    c[2].metric("Unexplained residual", f"{split['ntl_pct_est']:.2f}%")
    c[2].caption(f"Reference period: {metrics['technical_loss']['split_history']['ntl_pct_est']:.2f}%")
    c[3].metric("Corridor transmission loss", f"{metrics['technical_loss']['corridor']['transmission_loss_pct']:.2f}%")

    left, right = st.columns([3, 2])
    with left:
        heat = data.read_parquet(data.THEFT_DIR / "feeder_residual_heatmap.parquet")
        if heat is not None:
            h = heat.set_index("node_id")
            h.columns = [f"wk {int(c) + 1}" for c in h.columns]
            fig = px.imshow(h, aspect="auto", color_continuous_scale="OrRd", origin="upper",
                            labels=dict(color="residual %"), title="Unexplained loss by feeder and week (% of input)")
            fig.update_layout(height=520, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, width="stretch")
    with right:
        fig = go.Figure(go.Pie(labels=["Metered consumption", "Technical loss (est.)", "Suspected NTL (est. residual)"],
                               values=[split["metered_mwh"], split["technical_loss_pct_est"] * split["input_mwh"] / 100,
                                       split["ntl_pct_est"] * split["input_mwh"] / 100], hole=0.5))
        fig.update_layout(title="Where feeder energy went (scoring window)", height=300, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
        ratio = data.read_parquet(data.THEFT_DIR / "ntl_ratio_by_substation.parquet")
        if ratio is not None:
            st.markdown("**Suspected hidden load by corridor substation** (T9 hand-off)")
            st.dataframe(ratio.assign(est_pct=(100 * ratio.est_ntl_ratio).round(2), true_pct=(100 * ratio.true_ntl_ratio).round(2))
                         [["substation", "est_pct", "true_pct"]], hide_index=True, width="stretch")

    st.markdown("#### Ranked inspection list")
    leads = data.theft_leads()
    if leads:
        hide = st.toggle("Hash consumer IDs (shared demo)", value=True)
        show = lambda l: hashed_id(l["lead_id"]) if hide and l["lead_type"] == "consumer" else l["lead_id"]  # noqa: E731
        table = pd.DataFrame([{"rank": l["rank"], "lead": show(l), "type": l["lead_type"], "substation": l["substation"],
                               "DT": l["dt_id"], "score": l["score"], "interval": (f"{l['score_interval'][0]:.2f}-{l['score_interval'][1]:.2f}" if l.get("score_interval") else "-"), "confidence": l["confidence"],
                               "kWh at stake": l["expected_kwh_at_stake"]} for l in leads])
        st.dataframe(table, hide_index=True, width="stretch", height=320)
        pick = st.selectbox("Explain lead", [show(l) for l in leads])
        lead = next(l for l in leads if show(l) == pick)
        st.info(lead["summary"])
        for rc in lead["reason_codes"]:
            st.markdown(f"- {'➕' if rc['kind'] == 'supporting' else '➖'} **{rc['code']}** - {rc['text']}")
        if lead.get("similar_cases"):
            st.caption("Similar past cases: " + ", ".join(f"{hashed_id(s['case_id']) if hide else s['case_id']} ({s['outcome']}, {s['similarity']:.2f})"
                                                          for s in lead["similar_cases"]))
    strat = data.read_parquet(data.THEFT_DIR / "inspection_strategies.parquet")
    if strat is not None and role in ("Loss analyst", "Planner"):
        fig = px.bar(strat, x="strategy", y="recovered_kwh", text="hits",
                     title=f"Energy recovered by {int(strat.visits.max())} inspections (simulated truth; label = hits)")
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
    if role == "Loss analyst":
        fair = metrics.get("fairness", {}).get("operating_points", {}).get("threshold", {})
        if fair:
            st.markdown("#### False-positive audit (threshold 0.5)")
            st.dataframe(pd.DataFrame(fair["by_group"])[["group_by", "group", "n", "positives", "flag_rate", "fpr", "precision"]],
                         hide_index=True, width="stretch")
            st.caption(f"FPR disparity ratios: {fair['fpr_disparity_ratio']}")
