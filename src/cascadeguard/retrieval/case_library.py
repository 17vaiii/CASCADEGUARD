# OWNER: P5 | NEEDS: P2,P3 | STATUS: ACTIVE
"""R8 / P5-4: case-based retrieval over past cascade scenarios and their verified mitigations.

Each case stores the event, season, an embedding of the post-contingency state, the verified
actions and the outcome. Two embeddings are supported:

* ``physics`` - post-contingency line loadings, hydro deficit, tie availability and season
  (cheap: one power flow);
* ``gnn`` - the P3 ``CascadeGNN`` 128-d graph embedding of the pre-contingency snapshot with the
  initial trips flagged (read-only use of P3's checkpoint).

Search is exact cosine similarity locally; ``upsert_to_qdrant`` pushes the same vectors into
P2's ``cascade_cases`` Qdrant collection (vectors zero-padded to the collection size).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from cascadeguard.mitigation.network import Event, OperatingState, post_contingency

SEASONS = ("monsoon", "post_monsoon", "summer")


def physics_embedding(state: OperatingState, event: Event) -> np.ndarray:
    net, info = post_contingency(state, event)
    n = len(state.net.line)
    load = np.zeros(n)
    if info["converged"]:
        vals = net.res_line.loading_percent.fillna(0.0)
        vals[~net.line.in_service] = 0.0
        load[:] = vals.reindex(range(n)).fillna(0.0).to_numpy() / 100.0
        deficit = max(0.0, info.get("hydro_mw", 0.0) - state.hydro.max_mw) / 100.0
    else:
        deficit = 1.0
    tripped = np.zeros(n)
    tripped[list(event.lines)] = 1.0
    season = np.array([1.0 if state.season == s else 0.0 for s in SEASONS])
    extra = np.array([deficit, 1.0 if event.tie_loss else 0.0, info.get("island_shed_mw", 0.0) / 100.0])
    v = np.concatenate([load, 0.5 * tripped, 0.5 * season, extra])
    return v / max(np.linalg.norm(v), 1e-9)


def gnn_embedding(state: OperatingState, event: Event) -> np.ndarray | None:
    from cascadeguard.theft.hidden_load import _load_gnn, default_checkpoint, snapshot_from_net
    loaded = _load_gnn(str(default_checkpoint()))
    if loaded is None:
        return None
    from cascadeguard.cascade_ml.graph_builder import build_graph
    model = loaded[0]
    g = build_graph(snapshot_from_net(state.net, event.lines), include_targets=False)
    v = model.get_embedding(g).numpy().astype(float)
    return v / max(np.linalg.norm(v), 1e-9)


def action_signature(actions: dict[str, Any] | None, verified: bool) -> str:
    """Coarse action type used to judge whether a retrieved precedent is relevant."""
    if not verified:
        return "unmitigable"
    if actions is None:
        return "none"
    parts = []
    if abs(actions.get("tie_delta_mw", 0.0)) > 0.5:
        parts.append("tie_up" if actions["tie_delta_mw"] > 0 else "tie_down")
    parts += [f"shed:{b}" for b, v in sorted(actions.get("shed_mw", {}).items()) if v > 0.5]
    parts += ["switch"] if actions.get("open_lines") else []
    return "+".join(parts) or "none"


@dataclass
class CascadeCaseLibrary:
    kind: str = "physics"
    vectors: list[np.ndarray] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)

    def embed(self, state: OperatingState, event: Event) -> np.ndarray | None:
        return physics_embedding(state, event) if self.kind == "physics" else gnn_embedding(state, event)

    def add(self, state: OperatingState, event: Event, result: dict[str, Any], vector: np.ndarray | None = None) -> None:
        v = vector if vector is not None else self.embed(state, event)
        if v is None:
            return
        rec = result["recommendation"]
        from cascadeguard.mitigation.verifier import describe_actions
        before = result["before"]
        path = [s["name"] for s in before.get("trip_sequence", [])][:6]
        self.vectors.append(v)
        self.cases.append({
            "case_id": f"{state.season}|{state.label}|{event.label}", "season": state.season,
            "event": event.as_dict(), "stage": result["stage"], "verified": bool(rec["verified"]),
            "actions": rec["actions"], "signature": action_signature(rec["actions"], rec["verified"]),
            "before_lost_pct": before["load_lost_pct"], "after_lost_pct": rec["load_lost_pct"],
            "explanation": {"cascade_path": path, "critical_lines": before.get("critical_lines", [])[:3],
                            "actions": describe_actions(rec["actions"], rec, state)},
        })

    def query(self, vector: np.ndarray, k: int = 3, exclude: str | None = None) -> list[dict[str, Any]]:
        if not self.vectors:
            return []
        m = np.vstack(self.vectors)
        sims = m @ vector
        out = []
        for j in np.argsort(-sims):
            if exclude is not None and self.cases[j]["case_id"] == exclude:
                continue
            out.append({**self.cases[j], "similarity": float(sims[j])})
            if len(out) == k:
                break
        return out

    def store_vector(self, vector: np.ndarray, size: int) -> list[float]:
        """Vector for a fixed-size store: padded if short; if long, a seeded random projection
        (distances are approximately preserved; a plain cut would drop features)."""
        v = np.asarray(vector, dtype=float)
        if len(v) <= size:
            out = np.pad(v, (0, size - len(v)))
        else:
            proj = np.random.default_rng(1234).normal(size=(size, len(v))) / np.sqrt(size)
            out = proj @ v
        return (out / max(np.linalg.norm(out), 1e-9)).tolist()

    def upsert_to_qdrant(self, store: Any) -> int:
        size = int(getattr(store, "vector_size", 128))
        keys = ("season", "stage", "signature", "before_lost_pct", "after_lost_pct", "verified", "actions", "explanation")
        store.upsert("cascade_cases", [c["case_id"] for c in self.cases],
                     [self.store_vector(v, size) for v in self.vectors],
                     [{k: c[k] for k in keys} for c in self.cases])
        return len(self.cases)

    def query_qdrant(self, store: Any, vector: np.ndarray, k: int = 3) -> list[dict[str, Any]]:
        return store.search("cascade_cases", self.store_vector(vector, int(getattr(store, "vector_size", 128))), limit=k)


def precision_at_k(library: CascadeCaseLibrary, queries: list[tuple[np.ndarray, str]], k: int) -> float:
    """Share of the top-k retrieved cases whose action signature matches the query's own solution."""
    hits = []
    for vec, sig in queries:
        res = library.query(vec, k)
        if res:
            hits.append(np.mean([r["signature"] == sig for r in res]))
    return float(np.mean(hits)) if hits else float("nan")
