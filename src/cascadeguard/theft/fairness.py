# OWNER: P4 | STATUS: ACTIVE
"""P4-11: bias and false-positive audit by area and consumer category (PRD §7.5).

Wrongful flags harm consumers, so false-positive rates are reported per group at the operating
point actually used (top-K inspection list and a probability threshold). Disparity ratios
(max / min across groups) make uneven burden visible; they are reported, not hidden or tuned away.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def group_rates(df: pd.DataFrame, group_col: str, flag_col: str = "flagged",
                label_col: str = "is_theft") -> pd.DataFrame:
    rows = []
    for g, part in df.groupby(group_col):
        y, f = part[label_col].astype(bool), part[flag_col].astype(bool)
        neg, pos = (~y).sum(), y.sum()
        rows.append({
            "group_by": group_col, "group": g, "n": int(len(part)), "positives": int(pos),
            "flag_rate": float(f.mean()),
            "fpr": float((f & ~y).sum() / neg) if neg else float("nan"),
            "tpr": float((f & y).sum() / pos) if pos else float("nan"),
            "precision": float((f & y).sum() / f.sum()) if f.sum() else float("nan"),
            "base_rate": float(y.mean()),
        })
    return pd.DataFrame(rows)


def _ratio(series: pd.Series) -> float:
    s = series.dropna()
    s = s[s > 0]
    return float(s.max() / s.min()) if len(s) >= 2 else float("nan")


def fairness_report(scored: pd.DataFrame, k: int, threshold: float = 0.5,
                    groups: tuple[str, ...] = ("area", "consumer_type")) -> dict[str, Any]:
    """``scored`` needs ``prob``, ``is_theft`` and the group columns."""
    df = scored.copy()
    top = np.zeros(len(df), dtype=bool)
    top[np.argsort(-df.prob.to_numpy(), kind="stable")[:k]] = True
    report: dict[str, Any] = {"k": int(k), "threshold": threshold, "operating_points": {}}
    for name, flags in (("top_k", top), ("threshold", df.prob.to_numpy() >= threshold)):
        df["flagged"] = flags
        tables = [group_rates(df, g) for g in groups if g in df.columns]
        table = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
        report["operating_points"][name] = {
            "overall_fpr": float((flags & ~df.is_theft.astype(bool)).sum() / max((~df.is_theft.astype(bool)).sum(), 1)),
            "by_group": table.to_dict(orient="records"),
            "fpr_disparity_ratio": {g: _ratio(table[table.group_by == g].fpr) for g in groups if len(table)},
            "flag_rate_disparity_ratio": {g: _ratio(table[table.group_by == g].flag_rate) for g in groups if len(table)},
        }
    return report
