# OWNER: P5 | STATUS: ACTIVE
"""R11 copilot (retrieval, grounding, LLM fallbacks with a fake client), dashboard app and API route."""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import pytest

from cascadeguard.copilot.brief import build_facts, generate_brief
from cascadeguard.copilot.citations import check_brief
from cascadeguard.copilot.retriever import default_retriever, load_corpus

warnings.filterwarnings("ignore")

FACTS = build_facts({"label": "N-1 [5] + tie loss"}, "summer",
                    {"total_lost_mw": 177.7, "load_lost_pct": 42.9, "cascade": False, "ufls_mw": 168.1, "max_loading_pct": 104.7},
                    {"verified": True, "total_lost_mw": 123.1, "load_lost_pct": 29.7, "max_loading_pct": 55.7, "hydro_mw": 298.2},
                    "optimizer", ["Sharavathi hydro ramps up 80 MW.", "Shed 123 MW of load at PEENYA."],
                    {"base_mw": 218.2, "max_mw": 298.2, "ramp_limit_mw": 80.0})


def test_corpus_is_marked_and_chunked():
    passages = load_corpus()
    assert len({p.doc_id for p in passages}) >= 7 and len(passages) >= 14
    assert all(p.status for p in passages)
    assert all(p.status.startswith("illustrative") or p.status == "project document" for p in passages)


def test_retrieval_relevance():
    r = default_retriever()
    top = r.search("hydro ramp reservoir energy budget summer", 2)[0][0]
    assert top.doc_id == "hydro_operations"
    top = r.search("under-frequency load shedding generation deficit", 2)[0][0]
    assert top.doc_id == "load_shedding"


def test_facts_have_no_fake_citations():
    assert "[" not in FACTS["event"]


def test_extractive_brief_is_grounded():
    out = generate_brief(FACTS, use_llm=False)
    assert out["mode"] == "extractive" and out["requires_operator_approval"]
    assert any(c["cited"] for c in out["citations"])
    check = check_brief(out["brief"], str(FACTS), {c["n"]: c["snippet"] for c in out["citations"]})
    assert not check["invalid_citations"]
    assert "approve" in out["brief"].lower() and "confirmed" not in out["brief"].lower()


def test_grounding_check_flags_invented_numbers():
    res = check_brief("Shedding 999 MW will definitely prevent collapse [1].", "{'x': 5}", {1: "text"})
    assert 999.0 in res["unsupported_numbers"] and res["overclaims"] and not res["grounded"]
    res = check_brief("See [7].", "{}", {1: "text"})
    assert res["invalid_citations"] == [7] and "[7]" not in res["text"]


class _FakeMessages:
    def __init__(self, text: str, stop: str = "end_turn"):
        self.text, self.stop, self.calls = text, stop, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=self.text)])


def _client(text: str, stop: str = "end_turn"):
    msgs = _FakeMessages(text, stop)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_llm_path_with_fake_client():
    retrieved = generate_brief(FACTS, use_llm=False)["citations"]
    n = retrieved[0]["n"]
    good = (f"In summer the tie loss would cost 177.7 MW. The verified plan ramps hydro 80 MW and sheds 123 MW "
            f"at PEENYA, leaving 29.7% lost [{n}]. The operator must review and approve every action.")
    client, msgs = _client(good)
    out = generate_brief(FACTS, use_llm=True, client=client)
    assert out["mode"] == "llm" and out["model"] == "claude-opus-5-5"
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"] and "temperature" not in call


def test_llm_refusal_and_ungrounded_fall_back():
    client, _ = _client("", "refusal")
    out = generate_brief(FACTS, use_llm=True, client=client)
    assert out["mode"] == "extractive" and any("declined" in w for w in out["warnings"])
    client, _ = _client("Shed 999 MW now; this is guaranteed to work.")
    out = generate_brief(FACTS, use_llm=True, client=client)
    assert out["mode"] == "extractive" and any("grounding" in w for w in out["warnings"])


def test_dashboard_renders_two_separate_workspaces():
    from streamlit.testing.v1 import AppTest
    from cascadeguard.mitigation import REPO_ROOT
    at = AppTest.from_file(str(REPO_ROOT / "src" / "cascadeguard" / "dashboard" / "app.py"), default_timeout=300)
    at.run()
    assert not at.exception
    assert at.sidebar.radio[0].value == "Simulation Control Center"
    assert any("Corridor network" in e.value for e in at.markdown if hasattr(e, "value"))
    at.sidebar.radio[0].set_value("Manager Dashboard").run()
    assert not at.exception
    assert any(e.value == "## Manager Dashboard" for e in at.markdown if hasattr(e, "value"))
    assert any("Sharavathi–Bengaluru network" in e.value for e in at.markdown if hasattr(e, "value"))


def test_mitigate_api_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import cascadeguard.api.audit as audit
    from cascadeguard.api.main import app
    monkeypatch.setattr(audit, "DEFAULT_DB", tmp_path / "audit.sqlite3")
    client = TestClient(app)
    res = client.post("/api/mitigate", json={"snapshot": {"season": "post_monsoon", "lines": [0]},
                                             "options": {"brief": True}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["recommendation"]["verified"] and body["requires_operator_approval"]
    assert body["brief"]["mode"] in ("extractive", "llm")
    rec = client.get(f"/api/audit/recommendations/{body['audit_id']}").json()
    assert rec["verification"]["verified"] is True
    assert client.post("/api/mitigate", json={"snapshot": {"season": "winter", "lines": [0]}}).status_code == 422
