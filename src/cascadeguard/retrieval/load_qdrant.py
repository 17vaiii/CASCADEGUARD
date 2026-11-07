# OWNER: P5 | NEEDS: P2,P4 | STATUS: ACTIVE
"""Load the cascade and theft case bases into Qdrant and check that retrieval works (R8, T10, P4).

Start Qdrant first (``docker compose --profile local-platform up qdrant`` or any Qdrant 1.12), then:

    PYTHONPATH=src python -m cascadeguard.retrieval.load_qdrant --url http://localhost:6333

Writes ``cascade_cases`` and ``theft_cases`` and prints a search check for each collection.
"""

from __future__ import annotations

import argparse
import pickle
from typing import Any

import joblib
import numpy as np

from cascadeguard.mitigation import REPO_ROOT


def load_all(store: Any) -> dict[str, Any]:
    """Upsert both case bases; returns counts and whether a known case finds itself first."""
    store.ensure_collections()
    report: dict[str, Any] = {}
    lib_path = REPO_ROOT / "data" / "models" / "mitigation" / "cascade_case_library.pkl"
    if lib_path.exists():
        with open(lib_path, "rb") as fh:
            lib = pickle.load(fh)
        n = lib.upsert_to_qdrant(store)
        hits = 0
        for i in range(0, n, max(1, n // 20)):
            top = lib.query_qdrant(store, lib.vectors[i], 1)
            hits += bool(top) and top[0]["payload"]["external_id"] == lib.cases[i]["case_id"]
        report["cascade_cases"] = {"points": n, "self_hit_checks": len(range(0, n, max(1, n // 20))), "self_hits": int(hits)}
    bundle_path = REPO_ROOT / "data" / "models" / "theft" / "theft_bundle.joblib"
    if bundle_path.exists():
        base = joblib.load(bundle_path)["case_base"]
        base.vector_size = int(getattr(store, "vector_size", 128))
        n = base.upsert_to_qdrant(store)
        vecs = base.padded_vectors()
        ids = [str(c) for c in base.cases.iloc[:, 0]]
        checks = list(range(0, n, max(1, n // 20)))
        hits = 0
        for i in checks:
            top = store.search("theft_cases", vecs[i].tolist(), limit=1)
            hits += bool(top) and top[0]["payload"]["external_id"] == ids[i]
        report["theft_cases"] = {"points": n, "self_hit_checks": len(checks), "self_hits": int(hits)}
    return report


def main() -> None:
    from cascadeguard.retrieval.case_store import QdrantCaseStore
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=None)
    a = p.parse_args()
    print(load_all(QdrantCaseStore(url=a.url)))


if __name__ == "__main__":
    main()
