# OWNER: P5 | NEEDS: P3,P4 | STATUS: ACTIVE
"""Results view: headline metrics for both pillars (PRD demo step 6)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cascadeguard.dashboard import data
from cascadeguard.mitigation import REPO_ROOT


def render() -> None:
    st.subheader("📊 Grid Study Results & Performance Benchmarks")
    mit = data.read_json(data.MITIGATION_METRICS)
    if mit:
        st.markdown("**🛡️ Remedial Action Performance (Outages with Unmitigated Load Loss)**")
        st.caption("Benchmark metrics comparing unmitigated outages, heuristic redispatch, and verified MILP optimization across operating seasons.")
        rows = [{"season": r["season"].replace("_", " ").title(), "events": r["events"], "need action": r["needing_mitigation"],
                 "no action %": r.get("before_mean_lost_pct"), "greedy %": r.get("greedy_mean_lost_pct"),
                 "optimizer %": r.get("opt_mean_lost_pct"), "verified %": 100 * r["opt_pass_rate"] if "opt_pass_rate" in r else None}
                for r in mit["mitigation"]]
        st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, width="stretch")
        ws = mit.get("retrieval", {}).get("warm_start")
        if ws:
            st.info(f"⚡ Case-Based Warm Start: **{ws['speedup']:.1f}x faster** than cold optimization, "
                    f"pass rate **{100 * ws['warm_pass_rate']:.0f}%** (cold {100 * ws['cold_pass_rate']:.0f}%).")
        link = mit.get("theft_aware_mitigation", {})
        if link.get("status") == "ok" and link.get("events_needing_mitigation_on_truth"):
            st.write(f"Theft-aware planning ({link['season']}, {link['true_hidden_mw']:.1f} MW hidden load): "
                     f"**{link['aware_plans_verified_on_truth']} of {link['events_needing_mitigation_on_truth']}** plans verified on the true state, "
                     f"vs {link['scada_plans_verified_on_truth']} for SCADA-only plans.")
    else:
        st.caption("Run `python -m cascadeguard.mitigation.experiment` for mitigation results.")
    table = REPO_ROOT / "docs" / "results_table.md"
    if table.exists():
        with st.expander("📋 Shared Results Reference (docs/results_table.md)", expanded=not mit):
            st.markdown(table.read_text(encoding="utf-8"))
