# OWNER: P4 | NEEDS: P2,P5 | STATUS: ACTIVE
"""T10: case-based retrieval of similar past (simulated-confirmed) theft cases for each lead.

The case base holds inspected consumers from the reference population with their outcome
(confirmed theft type, or a legitimate explanation such as rooftop solar / vacancy). Each case
is a standardised behaviour + tamper + network-context vector. For a new lead the nearest
cases (cosine similarity) are shown as precedent: "3 of 5 most similar past cases were confirmed
meter bypass". It supports, never replaces, the inspection decision.

Vectors are zero-padded to the P2 Qdrant ``theft_cases`` collection size (default 128), so the
same cases can be upserted with :class:`cascadeguard.retrieval.case_store.QdrantCaseStore`.
A local exact search is used when Qdrant is not running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler

from cascadeguard.theft.features import BEHAVIOUR_COLUMNS

CASE_COLUMNS = BEHAVIOUR_COLUMNS + ["f_tamper_strong_recent", "f_tamper_total_recent", "f_feeder_z", "f_dt_z"]


@dataclass
class TheftCaseBase:
    columns: list[str] = field(default_factory=lambda: list(CASE_COLUMNS))
    vector_size: int = 128
    imputer: Any = None
    scaler: Any = None
    vectors: np.ndarray | None = None
    cases: pd.DataFrame | None = None

    def _encode(self, features: pd.DataFrame, fit: bool = False) -> np.ndarray:
        x = features.reindex(columns=self.columns).to_numpy(dtype=float)
        zcols = [i for i, c in enumerate(self.columns) if c in ("f_feeder_z", "f_dt_z")]
        x[:, zcols] = np.sign(x[:, zcols]) * np.log1p(np.abs(x[:, zcols]))   # z-scores can be huge
        if fit:
            self.imputer, self.scaler = SimpleImputer(strategy="median"), RobustScaler()
            x = self.scaler.fit_transform(self.imputer.fit_transform(x))
        else:
            x = self.scaler.transform(self.imputer.transform(x))
        x = np.clip(x, -8, 8)
        norm = np.linalg.norm(x, axis=1, keepdims=True)
        return x / np.maximum(norm, 1e-9)

    def fit(self, features: pd.DataFrame, outcomes: pd.DataFrame) -> "TheftCaseBase":
        """``outcomes`` indexed like ``features`` with ``outcome`` (theft type or legit reason)."""
        self.vectors = self._encode(features, fit=True)
        self.cases = outcomes.reindex(features.index).reset_index()
        return self

    def query(self, features: pd.DataFrame, k: int = 5) -> list[list[dict[str, Any]]]:
        q = self._encode(features)
        sims = q @ self.vectors.T
        out = []
        for row, qid in zip(sims, features.index):
            order = np.argsort(-row)
            items = []
            for j in order:
                case = self.cases.iloc[j]
                if case.iloc[0] == qid:           # never return the lead itself
                    continue
                items.append({"case_id": str(case.iloc[0]), "similarity": round(float(row[j]), 4),
                              "outcome": str(case.outcome)})
                if len(items) == k:
                    break
            out.append(items)
        return out

    def precedent_summary(self, matches: list[dict[str, Any]]) -> dict[str, Any]:
        outcomes = pd.Series([m["outcome"] for m in matches])
        theft = outcomes[~outcomes.isin(["no_theft", "rooftop_solar", "new_appliance", "vacancy"])]
        return {"k": len(matches), "confirmed_theft_share": float(len(theft) / max(len(matches), 1)),
                "outcomes": outcomes.value_counts().to_dict()}

    def padded_vectors(self) -> np.ndarray:
        """Case vectors zero-padded to ``vector_size`` for the P2 Qdrant ``theft_cases`` collection."""
        v = self.vectors
        if v.shape[1] > self.vector_size:
            raise ValueError("case vector longer than the Qdrant collection size")
        return np.pad(v, ((0, 0), (0, self.vector_size - v.shape[1])))

    def upsert_to_qdrant(self, store: Any) -> int:
        """Push cases into ``theft_cases`` using P2's ``QdrantCaseStore`` (when Qdrant runs)."""
        vecs = self.padded_vectors()
        ids = [str(c) for c in self.cases.iloc[:, 0]]
        payloads = [{"outcome": str(o)} for o in self.cases.outcome]
        store.upsert("theft_cases", ids, vecs.tolist(), payloads)
        return len(ids)


def outcome_labels(consumers: pd.DataFrame) -> pd.DataFrame:
    """Simulated inspection outcome per consumer: theft type, legit look-alike or ``no_theft``."""
    outcome = np.where(consumers.theft_type != "none", consumers.theft_type,
                       np.where(consumers.lookalike_type != "none", consumers.lookalike_type, "no_theft"))
    return pd.DataFrame({"outcome": outcome}, index=pd.Index(consumers.consumer_id, name="consumer_id"))


def retrieval_precision(base: TheftCaseBase, features: pd.DataFrame, outcomes: pd.Series, k: int = 5) -> dict[str, float]:
    """Precision@k: share of retrieved cases whose outcome matches the query's true outcome,
    for queries that are thefts (does the precedent point at the right theft type?)."""
    matches = base.query(features, k)
    same, theft_hit = [], []
    for m, truth in zip(matches, outcomes.reindex(features.index)):
        got = [x["outcome"] for x in m]
        same.append(np.mean([g == truth for g in got]) if got else 0.0)
        theft_hit.append(np.mean([g not in ("no_theft", "rooftop_solar", "new_appliance", "vacancy") for g in got]) if got else 0.0)
    return {"same_outcome_precision_at_k": float(np.mean(same)), "theft_precedent_share": float(np.mean(theft_hit)), "k": k}
