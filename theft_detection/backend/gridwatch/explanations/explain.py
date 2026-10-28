"""Alert explanations and inspection prioritisation.

Explanations are generated from the actual evidence of the selected alert:
  * rule alerts      -> the rule's conditions with observed values and thresholds
  * Random Forest    -> exact additive per-feature contributions for this prediction
                        (path decomposition, Saabas 2014): score = base + sum(contributions)
  * Isolation Forest -> which (one-sided) features are most unusual relative to the training
                        data, in robust z-units. This is a descriptive heuristic, not an
                        attribution of the IF score.

The pattern sentences ("consistent with ...") are documented heuristics that list the
explanations compatible with the evidence; they never conclude that theft occurred.

Inspection priority (decision support only):
  DQ  data-quality review    reading coverage < 80 % (consumer) / < 90 % (boundary)
  P1  field inspection, high flagged AND boundary energy imbalance >= 2 sigma, persistent
  P2  field inspection, med  flagged with partial corroboration
  P3  desk review            flagged but the energy balance does not corroborate it
"""

from __future__ import annotations

import numpy as np

from ..detection.bundle import ModelBundle
from ..detection.methods import (
    CONSUMER_METHODS, IF_COMBINED_FEATURES, IF_CONSUMER_FEATURES, UNIT_METHODS, one_sided, select,
)
from ..features.build import COMBINED_FEATURES, CONSUMER_FEATURES, FEATURE_DESCRIPTIONS, UNIT_FEATURES

PRIORITY_LABELS = {
    "P1": "Field inspection — high priority",
    "P2": "Field inspection — medium priority",
    "P3": "Desk review — evidence not corroborated",
    "DQ": "Meter-data review — data quality insufficient",
}
PRIORITY_WEIGHT = {"P1": 3.0, "P2": 2.0, "P3": 1.0, "DQ": 0.5}


def rf_contributions(rf, x: np.ndarray) -> tuple[float, np.ndarray]:
    """Exact additive decomposition of a RandomForest class-1 score for one sample."""
    contrib = np.zeros(len(x))
    bias = 0.0
    cls = list(rf.classes_).index(1) if 1 in rf.classes_ else None
    for est in rf.estimators_:
        t = est.tree_
        val = t.value[:, 0, :]
        frac = val / np.maximum(val.sum(axis=1, keepdims=True), 1e-12)
        p = frac[:, cls] if cls is not None else np.zeros(len(frac))
        node = 0
        bias += p[0]
        while t.children_left[node] != -1:
            f = t.feature[node]
            nxt = t.children_left[node] if x[f] <= t.threshold[node] else t.children_right[node]
            contrib[f] += p[nxt] - p[node]
            node = nxt
    n = len(rf.estimators_)
    return bias / n, contrib / n


def _fmt_pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def feature_evidence(bundle: ModelBundle, method: str, x_full: np.ndarray, level: str = "consumer",
                     top: int = 6) -> dict:
    """Per-feature evidence for a single scored sample."""
    if level != "consumer":
        if method == "rf_unit_combined":
            base, c = rf_contributions(bundle.rf_unit[level], x_full)
            order = np.argsort(-np.abs(c))[:top]
            return {"kind": "rf_contributions", "base_score": float(base),
                    "items": [{"feature": UNIT_FEATURES[i], "description": FEATURE_DESCRIPTIONS.get(UNIT_FEATURES[i]),
                               "value": float(x_full[i]), "contribution": float(c[i])} for i in order]}
        return {"kind": "none", "items": []}
    if method in ("rf_consumer", "rf_combined"):
        names = CONSUMER_FEATURES if method == "rf_consumer" else COMBINED_FEATURES
        xs = select(x_full[None, :], COMBINED_FEATURES, names)[0]
        rf = bundle.rf_consumer if method == "rf_consumer" else bundle.rf_combined
        base, c = rf_contributions(rf, xs)
        order = np.argsort(-np.abs(c))[:top]
        return {"kind": "rf_contributions", "base_score": float(base),
                "items": [{"feature": names[i], "description": FEATURE_DESCRIPTIONS.get(names[i]),
                           "value": float(xs[i]), "contribution": float(c[i])} for i in order]}
    if method in ("if_consumer", "if_combined"):
        names = IF_CONSUMER_FEATURES if method == "if_consumer" else IF_COMBINED_FEATURES
        xo = one_sided(x_full[None, :], COMBINED_FEATURES, names)[0]
        med, mad = bundle.if_feature_ref[method]
        rz = (xo - med) / (1.4826 * mad)
        order = np.argsort(-rz)[:top]
        return {"kind": "if_robust_z", "note": "Descriptive: how unusual each one-sided feature is versus the "
                                               "training data (robust z). Not an attribution of the IF score.",
                "items": [{"feature": names[i], "description": FEATURE_DESCRIPTIONS.get(names[i]),
                           "value": float(x_full[COMBINED_FEATURES.index(names[i])]), "robust_z": float(rz[i])}
                          for i in order]}
    return {"kind": "none", "items": []}


# ---------------------------------------------------------------------------------------
def consumer_priority(f: dict, i: int, dt_z72: float, completeness_72: float) -> tuple[str, list[str]]:
    why = []
    if completeness_72 < 0.8:
        why.append(f"only {_fmt_pct(completeness_72)} of the last 72 h readings were received")
        return "DQ", why
    days = int(f["days_below_75"][i])
    if dt_z72 >= 2.0:
        why.append(f"the DT energy balance shows unexplained energy of {dt_z72:.1f} sigma over 72 h")
        if days >= 2:
            why.append(f"the deviation has persisted for {days} consecutive days")
            return "P1", why
        why.append("but the deviation is recent (< 2 days)")
        return "P2", why
    if dt_z72 >= 1.0:
        why.append(f"the DT energy balance gives weak corroboration ({dt_z72:.1f} sigma)")
        return "P2", why
    why.append(f"the DT energy balance does not corroborate it ({dt_z72:.1f} sigma), which is also compatible "
               "with a genuine drop in consumption")
    return "P3", why


def unit_priority(kind: str, bal24: dict, j: int, days: int, coverage: float, gap_frac: float) -> tuple[str, list[str]]:
    why = []
    if coverage < 0.9 or gap_frac > 0.1:
        why.append(f"data quality is insufficient (coverage {_fmt_pct(coverage)}, input-meter gaps "
                   f"{_fmt_pct(gap_frac)} of hours)")
        return "DQ", why
    z = float(bal24["z"][j])
    if z >= 3.0 and days >= 1:
        why.append(f"unexplained energy is {z:.1f} sigma and has been significant for {days} whole day(s)")
        return "P1", why
    if z >= 2.0:
        why.append(f"unexplained energy is {z:.1f} sigma over 24 h")
        return "P2", why
    why.append(f"the 24 h energy balance is not significant on its own ({z:.1f} sigma)")
    return "P3", why


# ---------------------------------------------------------------------------------------
def explain_consumer(ctx, ft: dict, i: int, method: str, score: float, threshold: float, bundle: ModelBundle,
                     score_display: str) -> dict:
    d = ctx.data
    f = ft["consumer_raw"]
    cid = d.consumer_ids[i]
    dt = d.dt_ids[d.consumer_dt_idx[i]]
    fid = d.feeder_ids[d.consumer_feeder_idx[i]]
    k_dt = d.consumer_dt_idx[i]
    dtb72 = ft["units"]["dt"]["balance"][72]
    dt_z72 = float(dtb72["z"][k_dt])
    dt_u72 = float(dtb72["unexplained"][k_dt])
    dt_in72 = float(dtb72["input"][k_dt])
    comp72 = float(ft["completeness_72"][i])
    obs, exp = float(f["obs_72"][i]), float(f["exp_72"][i])
    pk = float(f["peak_ratio_72"][i])
    op = float(f["offpeak_ratio_72"][i])
    days = int(f["days_below_75"][i])
    level, why = consumer_priority(f, i, dt_z72, comp72)
    info = CONSUMER_METHODS[method]

    sentences = [
        f"{cid} ({d.consumer_category[i]}, supplied by {dt} on feeder {fid}) was flagged by the "
        f"{info['name']} with {score_display} (decision threshold {threshold:.3g}).",
        f"Over the last 72 h its recorded consumption was {obs:.1f} kWh against an expected {exp:.1f} kWh "
        f"({_fmt_pct(float(f['ratio_72'][i]))} of its own profile; {_fmt_pct(float(f['peer_ratio_72'][i]))} after "
        f"adjusting for peers on the same feeder).",
    ]
    if pk < op - 0.15:
        sentences.append(f"The shortfall is concentrated in its usual high-consumption hours (peak-hour ratio "
                         f"{_fmt_pct(pk)} vs {_fmt_pct(op)} at other hours).")
    if days >= 1:
        sentences.append(f"Daily consumption has been below 75 % of expected for {days} consecutive day(s).")
    if dt_z72 >= 2.0:
        sentences.append(f"{dt}'s energy balance shows {dt_u72:.1f} kWh unexplained over 72 h "
                         f"({_fmt_pct(dt_u72 / dt_in72) if dt_in72 > 0 else 'n/a'} of DT input, {dt_z72:.1f} sigma), "
                         "which is consistent with energy being drawn but not recorded inside this DT boundary.")
    else:
        sentences.append(f"{dt}'s energy balance shows no significant unexplained energy ({dt_z72:.1f} sigma), so a "
                         "genuine reduction in consumption (e.g. vacancy or reduced operation) is a plausible "
                         "explanation.")
    if comp72 < 0.98:
        sentences.append(f"{_fmt_pct(comp72)} of the expected readings in the last 72 h were received.")
    sentences.append("This is a screening result on synthetic data, not a finding of theft.")
    x_full = ft["consumer_X"][i]
    return {
        "kind": "consumer", "id": cid, "feeder": fid, "dt": dt, "category": str(d.consumer_category[i]),
        "method": method, "method_name": info["name"], "score": score, "threshold": threshold,
        "score_display": score_display,
        "priority": {"level": level, "label": PRIORITY_LABELS[level], "reasons": why},
        "text": " ".join(sentences),
        "evidence": {
            "observed_kwh_72h": obs, "expected_kwh_72h": exp, "ratio_72h": float(f["ratio_72"][i]),
            "peer_ratio_72h": float(f["peer_ratio_72"][i]), "peak_ratio_72h": pk, "offpeak_ratio_72h": op,
            "days_below_75pct": days, "completeness_72h": comp72, "dt_unexplained_kwh_72h": dt_u72,
            "dt_z_72h": dt_z72, "deficit_kwh_168h": float(ft["deficit_168"][i]),
        },
        "features": feature_evidence(bundle, method, x_full, "consumer"),
        "energy_at_stake_kwh_per_day": max(0.0, (exp - obs) / 3.0),
    }


def explain_unit(ctx, ft: dict, kind: str, j: int, method: str, score: float, threshold: float,
                 bundle: ModelBundle, score_display: str, consumer_flags: np.ndarray) -> dict:
    d = ctx.data
    ids = d.dt_ids if kind == "dt" else d.feeder_ids
    uid = ids[j]
    u = ft["units"][kind]
    b24, b168 = u["balance"][24], u["balance"][168]
    raw = u["raw"]
    days = int(u["days_imbalanced"][j])
    cov = float(raw["coverage_24"][j])
    gap_frac = float(raw["input_gap_frac_24"][j])
    level, why = unit_priority(kind, b24, j, days, cov, gap_frac)
    info = UNIT_METHODS[method]
    label = "DT" if kind == "dt" else "Feeder"
    U, E, z = float(b24["unexplained"][j]), float(b24["input"][j]), float(b24["z"][j])
    sentences = [
        f"{label} {uid} was flagged by the {info['name']} with {score_display} (decision threshold {threshold:.3g}).",
        f"Over the last 24 h: input {E:.1f} kWh, metered {float(b24['metered'][j]):.1f} kWh, imputed for missing "
        f"readings {float(b24['imputed'][j]):.1f} kWh, estimated technical losses {float(b24['loss_est'][j]):.1f} kWh "
        f"-> unexplained {U:.1f} kWh ({_fmt_pct(U / E) if E > 0 else 'n/a'} of input, {z:.1f} sigma).",
    ]
    if days >= 1:
        sentences.append(f"The unexplained energy has been significant (>= 2 sigma) for {days} consecutive day(s).")
    members = (d.consumer_dt_idx == j) if kind == "dt" else (d.consumer_feeder_idx == j)
    flagged = [str(d.consumer_ids[i]) for i in np.flatnonzero(members & consumer_flags)]
    share = float(raw["deficit_to_gap_168"][j])
    if kind == "feeder":
        dts = [k for k, x in enumerate(d.dt_ids) if d.topo.dts[x].feeder == uid]
        zdt = ft["units"]["dt"]["balance"][24]["z"]
        top = max(dts, key=lambda k: zdt[k])
        sentences.append(f"Within the feeder, {d.dt_ids[top]} carries the largest DT-level imbalance "
                         f"({float(ft['units']['dt']['balance'][24]['unexplained'][top]):.1f} kWh, {zdt[top]:.1f} sigma).")
    if cov < 0.9:
        sentences.append(f"Only {_fmt_pct(cov)} of consumer readings were received, so part of the gap may be an "
                         "imputation artefact; a meter-data review should precede any field visit.")
    elif float(b168["unexplained"][j]) > 0 and share >= 0.5:
        sentences.append(f"Consumer shortfalls inside the boundary account for about {_fmt_pct(min(share, 1.0))} of the "
                         f"7-day unexplained energy, consistent with under-recording at specific meters"
                         + (f" ({', '.join(flagged[:5])})." if flagged else "."))
    elif float(b168["unexplained"][j]) > 0 and share < 0.25:
        sentences.append("Consumer readings show no matching shortfall, which is consistent with load that does not "
                         "pass through any consumer meter (e.g. an unmetered connection), an error in the technical-"
                         "loss estimate, or an input-meter error.")
    sentences.append("Unexplained energy imbalance is an investigation signal, not proof of electricity theft.")
    return {
        "kind": kind, "id": uid, "feeder": uid if kind == "feeder" else d.topo.dts[uid].feeder,
        "dt": uid if kind == "dt" else None, "method": method, "method_name": info["name"], "score": score,
        "threshold": threshold, "score_display": score_display,
        "priority": {"level": level, "label": PRIORITY_LABELS[level], "reasons": why},
        "text": " ".join(sentences),
        "evidence": {
            "input_kwh_24h": E, "metered_kwh_24h": float(b24["metered"][j]), "imputed_kwh_24h": float(b24["imputed"][j]),
            "estimated_loss_kwh_24h": float(b24["loss_est"][j]), "unexplained_kwh_24h": U, "z_24h": z,
            "sigma_kwh_24h": float(b24["sigma"][j]), "unexplained_kwh_168h": float(b168["unexplained"][j]),
            "z_168h": float(b168["z"][j]), "days_significant": days, "coverage_24h": cov,
            "consumer_shortfall_share_of_gap_168h": share, "flagged_consumers": flagged,
        },
        "features": feature_evidence(bundle, method, u["X"][j], kind),
        "energy_at_stake_kwh_per_day": max(0.0, U),
    }
