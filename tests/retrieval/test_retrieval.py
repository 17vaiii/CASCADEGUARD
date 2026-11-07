# OWNER: P5 | STATUS: ACTIVE
"""R8 case library and P5-5 warm start."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from cascadeguard.mitigation.network import Event, build_state
from cascadeguard.mitigation.verifier import mitigate
from cascadeguard.retrieval.case_library import CascadeCaseLibrary, action_signature, precision_at_k
from cascadeguard.retrieval.warm_start import warm_mitigate

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def setup():
    st = build_state("post_monsoon")
    lib = CascadeCaseLibrary("physics")
    for li in (0, 2, 4, 20):
        ev = Event([li])
        lib.add(st, ev, mitigate(st, ev))
    return st, lib


def test_signatures():
    assert action_signature({"tie_delta_mw": 30.0, "shed_mw": {}}, True) == "tie_up"
    assert action_signature({"tie_delta_mw": 0.0, "shed_mw": {"PEENYA": 5.0}}, True) == "shed:PEENYA"
    assert action_signature({}, False) == "unmitigable"


def test_library_query_and_precision(setup):
    st, lib = setup
    v = lib.embed(st, Event([6]))
    assert np.isclose(np.linalg.norm(v), 1.0)
    hits = lib.query(v, 2)
    assert len(hits) == 2 and hits[0]["similarity"] >= hits[1]["similarity"]
    assert precision_at_k(lib, [(v, "tie_up")], 2) == 1.0


def test_warm_start_uses_precedent(setup):
    st, lib = setup
    res = warm_mitigate(st, Event([6]), lib, k=2)
    assert res["recommendation"]["verified"]
    assert res["stage"] in ("precedent_direct", "precedent_warm_optimizer")


def test_qdrant_padding(setup):
    _, lib = setup

    class FakeStore:
        vector_size = 256
        def upsert(self, collection, ids, vectors, payloads):
            self.args = (collection, ids, vectors, payloads)

    store = FakeStore()
    assert lib.upsert_to_qdrant(store) == 4
    assert store.args[0] == "cascade_cases" and all(len(v) == 256 for v in store.args[2])
