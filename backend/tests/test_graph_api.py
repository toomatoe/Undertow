"""GET /api/graph (app/graph via app.main): contract, filters, validation, empty DB, no network / no LLM."""

import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.db import Base, SessionLocal, engine
from app.graph import EVIDENCE_NOTE, clear_cache, llm
from app.main import app, state
from app.models import Article, ArticleTicker, Company
from app.schemas import Evidence

# No `with TestClient(...)`: skip the lifespan, which loads SEC data over the network
client = TestClient(app)

OFFERING = [
    "Pricing of underwritten public offering with warrants priced at market",
    "Offering priced: common shares and accompanying warrants",
    "Registered direct offering priced, warrants exercisable immediately",
    "Public offering of units priced; each unit includes warrants",
    "Prices offering of shares and pre-funded warrants",
    "Upsized offering priced with warrants for common shares",
]
CLINICAL = [
    "Positive phase 2 clinical trial results announced",
    "Clinical trial phase 3 topline results met primary endpoint",
    "Phase 1 clinical trial results show safety profile",
    "Interim results from phase 2 clinical trial presented",
    "Clinical trial results: phase 2b endpoint data",
    "Final phase 3 clinical trial results published",
]
TOP_KEYS = {"nodes", "edges", "clusters", "timeline", "params", "generated_at", "method"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network or LLM call from /api/graph")

    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "request", boom)  # (httpx.Client.send is what TestClient itself uses)
    monkeypatch.setattr(llm.LLMNamer, "__init__", boom)
    monkeypatch.setattr(llm.LLMNamer, "_ask", lambda self, info: boom())


@pytest.fixture(autouse=True)
def fresh_cache():
    clear_cache()
    yield
    clear_cache()


def seed():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with SessionLocal() as s:
        s.add_all([Company(symbol=f"OF{i}", cik=100 + i, name=f"Of {i}", size_bucket="micro") for i in range(6)])
        rows = []
        for i, t in enumerate(OFFERING):  # filings with a signal, published 2-7 h ago
            rows.append(Article(url=f"https://sec.gov/o{i}", url_hash=f"o{i}", title_hash=f"to{i}", title=t,
                                source="edgar", source_name="SEC EDGAR", form="424B5", published_at=now - timedelta(hours=2 + i),
                                signals=["offering_priced"], severity=2, sentiment=-0.4,
                                tickers=[ArticleTicker(symbol=f"OF{i}", method="edgar")]))
        for i, t in enumerate(CLINICAL):  # news, published 3-8 h ago
            rows.append(Article(url=f"https://wire.example/c{i}", url_hash=f"c{i}", title_hash=f"tc{i}", title=t,
                                source="rss", source_name="Wire", published_at=now - timedelta(hours=3 + i),
                                sentiment=0.5, tickers=[ArticleTicker(symbol=f"CT{i}", method="cashtag")]))
        s.add_all(rows)
        s.commit()


def setup_module():
    os.environ.pop("ANTHROPIC_API_KEY", None)
    assert not main.settings.enrich_enabled  # no key -> no Claude namer (LLMNamer is also patched to fail)
    seed()
    state.evidence = {
        ("offering_priced", "micro"): Evidence(signal="offering_priced", bucket="micro", n=40, horizon_days=20,
                                               mean_abnormal=-0.06, mean_net=0.03, t_stat=-2.9, significant=True),
    }


def teardown_module():
    state.evidence = {}


def get(**params):
    r = client.get("/api/graph", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_contract_shape():
    g = get(days=7)
    assert set(g) == TOP_KEYS
    assert len(g["nodes"]) == 12
    node = g["nodes"][0]
    assert {"id", "kind", "title", "url", "source_name", "form", "ticker", "tickers", "signals", "signal_labels",
            "severity", "size_bucket", "sentiment", "published_at", "cluster", "x", "y"} <= set(node)
    assert {n["kind"] for n in g["nodes"]} == {"filing", "news"}
    assert {e["type"] for e in g["edges"]} <= {"contextual", "spatial", "temporal"}
    assert g["edges"], "two coherent topics should be linked"
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids and 0 <= e["weight"] <= 1 for e in g["edges"])
    real = [c for c in g["clusters"] if c["id"] != -1]
    assert real
    c = real[0]
    assert c["name_source"] == "terms"  # no API key in tests -> no LLM namer
    assert c["evidence_note"] == EVIDENCE_NOTE
    assert set(g["params"]) == {"days", "max_nodes", "ticker", "source", "truncated", "total_in_window"}
    assert g["params"] == {"days": 7, "max_nodes": 400, "ticker": None, "source": "all", "truncated": False,
                           "total_in_window": 12}
    assert g["generated_at"].endswith("Z") or g["generated_at"].endswith("+00:00")
    assert node["published_at"].endswith("Z") or node["published_at"].endswith("+00:00")


def test_evidence_reuses_main_state():
    g = get(days=7)
    offering = [c for c in g["clusters"] if any(m["code"] == "offering_priced" for m in c["signal_mix"])]
    assert offering and offering[0]["evidence"]["mean_abnormal"] == -0.06
    assert offering[0]["evidence"]["forward_test"] is False
    assert all(c["evidence"] is None for c in g["clusters"] if c["id"] == -1)


def test_timeline_granularity():
    one = get(days=1)["timeline"]
    assert one["granularity"] == "hour"
    assert sum(sum(b["counts"].values()) for b in one["buckets"]) == 12
    assert get(days=7)["timeline"]["granularity"] == "day"


def test_ticker_filter_uppercased():
    g = get(ticker="of1")
    assert g["params"]["ticker"] == "OF1"
    assert [n["ticker"] for n in g["nodes"]] == ["OF1"]


def test_source_filter():
    filings = get(source="filings")
    assert filings["params"]["source"] == "filings"
    assert len(filings["nodes"]) == 6 and {n["kind"] for n in filings["nodes"]} == {"filing"}
    news = get(source="news")
    assert len(news["nodes"]) == 6 and {n["kind"] for n in news["nodes"]} == {"news"}


@pytest.mark.parametrize("query", [
    "days=0", "days=31", "max_nodes=5", "max_nodes=2000", "source=bogus", "ticker=bad%20ticker!", "ticker=",
    "ticker=ABCDEFGHIJKLM", "days=abc",
])
def test_validation_422(query):
    assert client.get(f"/api/graph?{query}").status_code == 422


def test_method_wording_associations_not_causes():
    g = get(days=7)
    note = g["method"]["note"]
    assert "not causes" in note
    assert "2408.11133" in note and "2602.02601" in note
    others = " ".join(v for k, v in g["method"].items() if k != "note").lower()
    assert "cause" not in others and "causal" not in others
    # The only 'cause' wording anywhere in the response is the negation in method.note
    text = json.dumps({k: v for k, v in g.items() if k != "method"}).lower()
    assert "causal" not in text and "caused" not in text


def test_empty_db():
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        g = get(days=7)
        assert g["nodes"] == [] and g["edges"] == [] and g["clusters"] == []
        assert g["params"]["total_in_window"] == 0 and g["params"]["truncated"] is False
        assert g["timeline"]["granularity"] == "day"
    finally:
        seed()


def test_fallback_evidence_without_loaded_state(monkeypatch):
    # Before the lifespan loads evidence, the endpoint uses build_graph's default (app.vault.make_evidence_fn).
    monkeypatch.setattr(state, "evidence", {})
    monkeypatch.setattr(state, "forward_evidence", None)
    g = get(days=7)
    assert len(g["nodes"]) == 12
