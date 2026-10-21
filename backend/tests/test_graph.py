"""Event graph engine (app/graph): TF-IDF, smoothing, clustering, edges, naming, evidence, timeline, cache.

In-memory SQLite; deterministic; never touches the network or the LLM (httpx and the anthropic client are patched
to fail, and every namer used here is a local fake).
"""

import json
import math
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.graph import EVIDENCE_NOTE, OTHER_NAME, GraphParams, build_graph, clear_cache
from app.graph import cluster, edges, llm, naming, service, smooth, text
from app.models import Article, ArticleTicker, Company
from app.newsletter.service import BANNED

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
PACKAGE = Path(service.__file__).parent
ORIGINAL_ASK = llm.LLMNamer._ask  # captured before the autouse fixture replaces it

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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call from the graph engine")

    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(llm.LLMNamer, "_ask", lambda self, info: boom())


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    clear_cache()


_n = 0


def add(s, title, *, ticker=None, when=None, source="edgar", signals=None, severity=None, sentiment=None,
        snippet=None, tickers=None, form=None):
    global _n
    _n += 1
    a = Article(
        url=f"https://example.com/{_n}", url_hash=f"u{_n}", title_hash=f"t{_n}", title=title, snippet=snippet,
        source=source, source_name="SEC EDGAR" if source == "edgar" else "Wire", published_at=when or NOW - timedelta(hours=1),
        form=form or ("424B5" if source == "edgar" else None), signals=signals, severity=severity, sentiment=sentiment,
    )
    a.tickers = [ArticleTicker(symbol=t, method="edgar") for t in (tickers or ([ticker] if ticker else []))]
    s.add(a)
    return a


def seed_topics(order=None, with_signals=True):
    rows = []
    for i, t in enumerate(OFFERING):
        rows.append(dict(title=t, ticker=f"OF{i}", when=NOW - timedelta(hours=2 + i),
                         signals=["offering_priced"] if with_signals else None, severity=2 if with_signals else None,
                         sentiment=-0.4))
    for i, t in enumerate(CLINICAL):
        rows.append(dict(title=t, ticker=f"CT{i}", when=NOW - timedelta(hours=3 + i), source="rss", sentiment=0.5))
    if order is not None:
        rows = [rows[i] for i in order]
    with SessionLocal() as s:
        s.add_all([Company(symbol=f"OF{i}", cik=100 + i, name=f"Of {i}", size_bucket="micro") for i in range(6)])
        for r in rows:
            add(s, **r)
        s.commit()


def graph(params=None, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("evidence_fn", lambda code, bucket: None)
    kw.setdefault("use_cache", False)
    with SessionLocal() as s:
        return build_graph(s, params or GraphParams(days=7), **kw)


def partition(g):
    by = {}
    for nd in g["nodes"]:
        by.setdefault(nd["cluster"], set()).add(nd["title"])
    return sorted((frozenset(v) for k, v in by.items() if k != -1), key=lambda f: sorted(f))


# --- text / TF-IDF ---------------------------------------------------------------------


def test_tfidf_hand_computed():
    vecs, vocab, idf, counts = text.tfidf(["alpha beta", "alpha gamma", "alpha delta beta"])
    idx = {t: i for i, t in enumerate(vocab)}
    assert vocab == sorted(vocab)
    assert "alpha beta" in idx and "delta beta" in idx  # bigrams
    assert idf[idx["alpha"]] == pytest.approx(1.0)
    assert idf[idx["beta"]] == pytest.approx(math.log(4 / 3) + 1)
    assert idf[idx["gamma"]] == pytest.approx(math.log(2) + 1)
    assert idf[idx["gamma"]] > idf[idx["beta"]] > idf[idx["alpha"]]
    raw = {"alpha": 1.0, "beta": math.log(4 / 3) + 1, "alpha beta": math.log(2) + 1}
    norm = math.sqrt(sum(v * v for v in raw.values()))
    assert vecs[0] == pytest.approx({idx[t]: v / norm for t, v in raw.items()})
    for v in vecs:
        assert math.sqrt(sum(w * w for w in v.values())) == pytest.approx(1.0)


def test_tokenizer_strips_stopwords_html_urls_numbers():
    toks = text.tokenize("<p>The Company, Inc. announced its Form 8-K filing</p> https://sec.gov/x 2026 Warrants &amp; SHARES")
    assert toks == ["warrants", "shares"]  # form codes such as 8-k are boilerplate (the signal label carries the form)
    assert "offering" not in text.STOPWORDS and "shares" not in text.STOPWORDS
    assert {"inc", "corp", "form", "filing", "sec", "company"} <= text.STOPWORDS


def test_min_df_relaxed_for_small_corpora_and_max_df_applied_on_large():
    _, vocab_small, _, _ = text.tfidf(["unique words here", "other text there"])
    assert "unique" in vocab_small  # n < 10 -> min_df 1
    docs = ["common rare%d" % i for i in range(12)] + ["pair x", "pair y"]
    _, vocab, _, _ = text.tfidf(docs)
    assert "common" not in vocab  # df 12/14 > 0.5
    assert "pair" in vocab and "rare3" not in vocab  # min_df 2


# --- similarity / smoothing ----------------------------------------------------------


def test_topk_and_smoothing():
    vecs, _, _, _ = text.tfidf(OFFERING + CLINICAL)
    nb = smooth.topk_neighbours(vecs, k=3)
    for i, lst in enumerate(nb):
        assert len(lst) <= 3 and all(j != i for j, _ in lst)
        assert all((j < 6) == (i < 6) for j, _ in lst)  # no shared terms across topics
        sims = [s for _, s in lst]
        assert sims == sorted(sims, reverse=True)
    h = smooth.smooth(vecs, nb, alpha=0.5, hops=2)
    for v in h:
        assert math.sqrt(sum(w * w for w in v.values())) == pytest.approx(1.0)
    # neighbours move closer: mean within-topic cosine increases
    def mean_within(vs):
        pairs = [(i, j) for i in range(6) for j in range(i + 1, 6)]
        return sum(smooth.cosine(vs[i], vs[j]) for i, j in pairs) / len(pairs)
    assert mean_within(h) > mean_within(vecs)
    assert smooth.smooth(vecs, nb, hops=0) == vecs


# --- clustering ------------------------------------------------------------------------


def test_clustering_separates_topics_and_is_deterministic():
    seed_topics()
    g1 = graph()
    g2 = graph()
    assert g1 == g2
    parts = partition(g1)
    assert parts == sorted([frozenset(OFFERING), frozenset(CLINICAL)], key=lambda f: sorted(f))
    assert all(nd["cluster"] in (0, 1) for nd in g1["nodes"])

    # shuffled insertion order -> same partition and the same names
    setup_function()
    order = list(range(12))
    random.Random(7).shuffle(order)
    seed_topics(order=order)
    g3 = graph()
    assert partition(g3) == parts
    assert sorted(c["name"] for c in g3["clusters"]) == sorted(c["name"] for c in g1["clusters"])


def test_louvain_tie_free_and_order_independent():
    e = [(0, 1, 1.0), (1, 2, 1.0), (0, 2, 1.0), (3, 4, 1.0), (4, 5, 1.0), (3, 5, 1.0), (2, 3, 0.1)]
    a = cluster.louvain(6, e)
    b = cluster.louvain(6, list(reversed(e)))
    assert a == b
    assert a[0] == a[1] == a[2] and a[3] == a[4] == a[5] and a[0] != a[3]


def test_small_groups_become_other():
    seed_topics()
    with SessionLocal() as s:
        add(s, "Bitcoin mining rigs expanded", ticker="BTC1", source="rss", when=NOW - timedelta(hours=5))
        add(s, "Bitcoin mining rigs acquired", ticker="BTC2", source="rss", when=NOW - timedelta(hours=6))
        add(s, "Lonely unrelated headline about weather", ticker="WX", source="rss", when=NOW - timedelta(hours=7))
        s.commit()
    g = graph()
    other = [nd for nd in g["nodes"] if nd["cluster"] == -1]
    assert {nd["title"] for nd in other} >= {"Lonely unrelated headline about weather"}
    assert all("Bitcoin" in nd["title"] or "Lonely" in nd["title"] for nd in other)
    assert g["clusters"][-1]["id"] == -1 and g["clusters"][-1]["name"] == OTHER_NAME
    assert g["clusters"][-1]["evidence"] is None
    sizes = [c["size"] for c in g["clusters"] if c["id"] != -1]
    assert sizes == sorted(sizes, reverse=True) and min(sizes) >= 3
    assert [c["id"] for c in g["clusters"] if c["id"] != -1] == list(range(len(sizes)))


# --- edges ---------------------------------------------------------------------------


def test_edge_types_direction_and_cap():
    with SessionLocal() as s:
        s.add(Company(symbol="AAA", cik=1, name="A", size_bucket="micro"))
        s.add(Company(symbol="BBB", cik=2, name="B", size_bucket="micro"))
        for i, t in enumerate(OFFERING):
            add(s, t, ticker="AAA" if i % 2 else "BBB", when=NOW - timedelta(hours=3 * i + 1),
                signals=["offering_priced"], severity=2)
        add(s, OFFERING[0] + " again", ticker="AAA", when=NOW - timedelta(days=5))  # outside 48h of the others
        s.commit()
    g = graph()
    by_id = {nd["id"]: nd for nd in g["nodes"]}
    types = {e["type"] for e in g["edges"]}
    assert {"contextual", "spatial", "temporal"} <= types
    for kind in ("contextual", "spatial"):
        pairs = [(e["source"], e["target"]) for e in g["edges"] if e["type"] == kind]
        assert all(a < b for a, b in pairs)
        assert len(pairs) == len(set(pairs))
    for e in g["edges"]:
        assert 0.0 <= e["weight"] <= 1.0
        if e["type"] == "temporal":
            gap = by_id[e["target"]]["published_at"] - by_id[e["source"]]["published_at"]
            assert timedelta(0) <= gap <= timedelta(hours=48)
        if e["type"] == "contextual":
            assert e["weight"] >= 0.2
    assert len(g["edges"]) <= 8 * len(g["nodes"])
    # same ticker = chain, not clique: AAA has 4 items -> 3 spatial ticker edges among them
    aaa = {nd["id"] for nd in g["nodes"] if nd["ticker"] == "AAA"}
    sp = [e for e in g["edges"] if e["type"] == "spatial" and e["weight"] == 1.0
          and e["source"] in aaa and e["target"] in aaa]
    assert len(sp) == len(aaa) - 1


def test_temporal_window_and_size_bucket_edges():
    t0 = NOW
    items = [edges.Item(0, t0, ["X"], "micro"), edges.Item(1, t0 + timedelta(hours=24), ["X"], "micro"),
             edges.Item(2, t0 + timedelta(hours=100), ["X"], "micro")]
    tmp = edges.temporal_edges(items, [0, 0, 0], 48)
    assert tmp == [("temporal", 0, 1, 0.5)]
    sb = edges.size_bucket_edges(items, [0, 0, 0], existing={(0, 1)})
    assert sb == [("spatial", 1, 2, 0.15)]
    assert edges.size_bucket_edges(items, [-1, -1, -1], existing=set()) == []


def test_cap_edges_keeps_strongest_per_type():
    es = [("contextual", i, i + 1, 0.2 + i / 1000) for i in range(100)] + \
         [("temporal", i, i + 1, 0.9 - i / 1000) for i in range(50)]
    kept = edges.cap_edges(es, 30)
    assert len(kept) == 30
    ctx = [e for e in kept if e[0] == "contextual"]
    tmp = [e for e in kept if e[0] == "temporal"]
    assert len(ctx) == 20 and len(tmp) == 10
    assert min(e[3] for e in ctx) > max(e[3] for e in es[:80])  # the 20 strongest contextual
    assert sorted(e[1] for e in tmp) == list(range(10))


# --- naming --------------------------------------------------------------------------


def test_terms_name_has_terms_signal_label_and_tickers():
    seed_topics()
    g = graph()
    off = next(c for c in g["clusters"] if "Offering priced (424B)" in c["name"])
    assert off["name_source"] == "terms"
    assert any(w in off["name"] for w in ("offering", "warrants", "priced"))
    assert off["tickers"][0] in off["name"]
    assert off["signal_mix"] == [{"code": "offering_priced", "label": "Offering priced (424B)", "count": 6}]
    assert off["mean_sentiment"] == pytest.approx(-0.4) and off["sentiment_n"] == 6
    clin = next(c for c in g["clusters"] if c is not off and c["id"] != -1)
    assert any(w in clin["name"] for w in ("clinical", "trial", "phase"))
    for c in g["clusters"]:
        assert not BANNED.search(c["name"])


def test_ctfidf_filters_non_neutral_and_redundant_terms():
    from collections import Counter

    out = naming.ctfidf_terms({0: Counter({"buyback": 9, "offering": 5, "offering priced": 5, "priced": 4, "warrants": 3}),
                               1: Counter({"trial": 5})})
    assert "buyback" not in out[0]
    assert len(out[0]) == 3 and len(set(" ".join(out[0]).split())) == len(" ".join(out[0]).split())


def test_fake_namer_failing_namer_and_bad_names():
    seed_topics()
    calls = []

    def fake(info):
        calls.append(info)
        assert set(info) >= {"id", "member_ids", "terms", "titles", "tickers", "signal_label"}
        return "Small-cap financing round-up"

    g = graph(namer=fake)
    real = [c for c in g["clusters"] if c["id"] != -1]
    assert calls and all(c["name_source"] == "llm" and c["name"] == "Small-cap financing round-up" for c in real)

    def failing(info):
        raise RuntimeError("down")

    assert all(c["name_source"] == "terms" for c in graph(namer=failing)["clusters"])
    assert all(c["name_source"] == "terms" for c in graph(namer=lambda i: "Stocks to buy now")["clusters"])
    assert all(c["name_source"] == "terms" for c in graph(namer=lambda i: "Offering caused the drop")["clusters"])
    long = graph(namer=lambda i: "x" * 200)["clusters"][0]
    assert long["name_source"] == "llm" and len(long["name"]) <= 60


def test_llm_namer_never_built_without_api_key(monkeypatch):
    assert not get_settings().enrich_enabled

    def boom(*a, **k):
        raise AssertionError("LLM namer constructed without an API key")

    monkeypatch.setattr(llm.LLMNamer, "__init__", boom)
    seed_topics()
    with SessionLocal() as s:
        g = build_graph(s, GraphParams(days=7), now=NOW, use_cache=False)
    assert g["clusters"] and all(c["name_source"] == "terms" for c in g["clusters"])
    assert llm.default_namer(SimpleNamespace(enrich_enabled=False)) is None


def test_llm_namer_with_fake_client_caches_to_data_dir(tmp_path, monkeypatch):
    sent = []

    def create(**kw):
        sent.append(kw)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps({"name": "Warrant offerings"}))])

    client = SimpleNamespace(messages=SimpleNamespace(create=create), beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm.LLMNamer, "_ask", ORIGINAL_ASK)  # undo the autouse guard; the client is a fake
    namer = llm.LLMNamer("test-key", "claude-opus-5-5", str(tmp_path), client=client)
    info = {"id": 0, "member_ids": [3, 1, 2], "terms": ["offering", "warrants"], "titles": ["t"] * 20,
            "tickers": ["AAA"], "signal_label": "Offering priced (424B)"}
    assert namer(info) == "Warrant offerings"
    assert namer(dict(info, member_ids=[1, 2, 3])) == "Warrant offerings"
    assert len(sent) == 1  # second call served from graph_names.json
    assert sent[0]["model"] == "claude-opus-5-5"
    assert sent[0]["messages"][0]["content"].count("\n- ") <= 12
    stored = json.loads((tmp_path / llm.CACHE_FILE).read_text())
    assert list(stored.values()) == ["Warrant offerings"]

    def broken(**kw):
        raise RuntimeError("api down")

    namer2 = llm.LLMNamer("k", "claude-opus-5-5", str(tmp_path / "other"),
                          client=SimpleNamespace(messages=SimpleNamespace(create=broken),
                                                 beta=SimpleNamespace(messages=SimpleNamespace(create=broken))))
    assert namer2(info) is None


# --- evidence / timeline ---------------------------------------------------------------


def test_evidence_fn_injected_and_attached():
    seed_topics()
    calls = []
    row = {"signal": "offering_priced", "bucket": "micro", "n": 90, "horizon_days": 20, "mean_abnormal": -0.02,
           "mean_net": 0.004, "excess_vs_baseline": None, "t_stat": -1.1, "significant": False}

    def ev(code, bucket):
        calls.append((code, bucket))
        return row if (code, bucket) == ("offering_priced", "micro") else None

    g = graph(evidence_fn=ev)
    off = next(c for c in g["clusters"] if c["signal_mix"])
    assert off["evidence"] == row
    assert ("offering_priced", "micro") in calls
    assert all(c["evidence_note"] == EVIDENCE_NOTE for c in g["clusters"])
    clin = next(c for c in g["clusters"] if c["id"] != -1 and not c["signal_mix"])
    assert clin["evidence"] is None


def test_timeline_granularity_and_counts():
    seed_topics()
    g7 = graph(GraphParams(days=7))
    assert g7["timeline"]["granularity"] == "day"
    assert len(g7["timeline"]["buckets"]) == 8
    g2 = graph(GraphParams(days=2))
    tl = g2["timeline"]
    assert tl["granularity"] == "hour" and len(tl["buckets"]) == 49
    for g in (g7, g2):
        total = sum(sum(b["counts"].values()) for b in g["timeline"]["buckets"])
        assert total == len(g["nodes"])
        assert all(v > 0 for b in g["timeline"]["buckets"] for v in b["counts"].values())
        ts = [b["t"] for b in g["timeline"]["buckets"]]
        assert ts == sorted(ts)


# --- selection / params / contract ------------------------------------------------------


def test_source_ticker_filters_and_truncation():
    seed_topics()
    with SessionLocal() as s:
        add(s, "Old item outside the window", ticker="OF0", when=NOW - timedelta(days=20))
        for i in range(15):
            add(s, f"Generic market wrap number {i}", source="rss", when=NOW - timedelta(minutes=10 + i))
        s.commit()
    filings = graph(GraphParams(days=7, source="filings"))
    assert {nd["kind"] for nd in filings["nodes"]} == {"filing"} and len(filings["nodes"]) == 6
    news = graph(GraphParams(days=7, source="news"))
    assert {nd["kind"] for nd in news["nodes"]} == {"news"} and len(news["nodes"]) == 21
    tk = graph(GraphParams(days=30, ticker="of0"))
    assert tk["params"]["ticker"] == "OF0" and {nd["ticker"] for nd in tk["nodes"]} == {"OF0"} and len(tk["nodes"]) == 2
    tr = graph(GraphParams(days=7, max_nodes=20))
    assert tr["params"] == {"days": 7, "max_nodes": 20, "ticker": None, "source": "all", "truncated": True,
                            "total_in_window": 27}
    assert len(tr["nodes"]) == 20
    assert sum(nd["kind"] == "filing" for nd in tr["nodes"]) == 6  # signal filings kept first
    assert [nd["id"] for nd in tr["nodes"]] == sorted(nd["id"] for nd in tr["nodes"])


def test_params_validation():
    for bad in (dict(days=0), dict(days=31), dict(max_nodes=19), dict(max_nodes=1001), dict(source="tweets"),
                dict(ticker="bad ticker!"), dict(ticker="TOOLONGTICKER1"), dict(hops=3)):
        with pytest.raises(ValueError):
            GraphParams(**bad)
    p = GraphParams(ticker=" brk.b ", source="FILINGS")
    assert p.ticker == "BRK.B" and p.source == "filings" and p.max_nodes == 400


def test_contract_shape_and_wording():
    seed_topics()
    g = graph()
    assert set(g) == {"nodes", "edges", "clusters", "timeline", "params", "generated_at", "method"}
    assert set(g["nodes"][0]) == {"id", "kind", "title", "url", "source_name", "form", "ticker", "tickers", "signals",
                                  "signal_labels", "severity", "size_bucket", "sentiment", "published_at", "cluster",
                                  "x", "y"}
    assert set(g["edges"][0]) == {"source", "target", "type", "weight"}
    assert set(g["clusters"][0]) == {"id", "name", "name_source", "terms", "size", "tickers", "signal_mix",
                                     "mean_sentiment", "sentiment_n", "start", "end", "evidence", "evidence_note"}
    assert set(g["method"]) == {"embedding", "smoothing", "clustering", "edges", "naming", "note"}
    assert g["generated_at"] == NOW
    assert all(nd["published_at"].tzinfo is not None for nd in g["nodes"])
    off = next(nd for nd in g["nodes"] if nd["kind"] == "filing")
    assert off["signals"] == ["offering_priced"] and off["signal_labels"] == ["Offering priced (424B)"]
    assert off["size_bucket"] == "micro" and off["x"] is None
    note = g["method"]["note"]
    assert "not causes" in note and "2408.11133" in note and "2602.02601" in note
    assert "not a trained GNN" in g["method"]["smoothing"]
    for v in g["method"].values():
        assert not BANNED.search(v)
        assert not re.search(r"\bcausal", v, re.I)
    json.dumps(g, default=str)


def test_empty_window():
    g = graph()
    assert g["nodes"] == [] and g["edges"] == [] and g["clusters"] == []
    assert g["params"]["total_in_window"] == 0 and not g["params"]["truncated"]
    assert len(g["timeline"]["buckets"]) == 8


# --- cache -------------------------------------------------------------------------------


def test_cache_hit_ttl_and_invalidation(monkeypatch):
    seed_topics()
    clock = [1000.0]
    monkeypatch.setattr(service, "_clock", lambda: clock[0])
    with SessionLocal() as s:
        a = build_graph(s, GraphParams(days=7), now=NOW)
        b = build_graph(s, GraphParams(days=7), now=NOW)
        assert a is b
        assert build_graph(s, GraphParams(days=3), now=NOW) is not a
        add(s, "Brand new filing", ticker="NEW", when=NOW - timedelta(minutes=5))
        s.commit()
        c = build_graph(s, GraphParams(days=7), now=NOW)
        assert c is not a and len(c["nodes"]) == len(a["nodes"]) + 1
        assert build_graph(s, GraphParams(days=7), now=NOW) is c
        clock[0] += service.CACHE_TTL_SECONDS + 1
        assert build_graph(s, GraphParams(days=7), now=NOW) is not c
        # injected callables bypass the cache
        assert build_graph(s, GraphParams(days=7), now=NOW, evidence_fn=lambda c, b: None) is not c
    assert len(service._cache) <= service.CACHE_MAX_ENTRIES


# --- performance / package hygiene ------------------------------------------------------------


def test_400_nodes_is_fast():
    rng = random.Random(1)
    topics = [[f"t{k}w{j}" for j in range(25)] for k in range(12)]
    noise = [f"noise{j}" for j in range(400)]
    with SessionLocal() as s:
        for i in range(400):
            words = rng.sample(topics[i % 12], 8) + rng.sample(noise, 4)
            add(s, " ".join(words), ticker=f"T{i % 90}", when=NOW - timedelta(minutes=17 * i),
                source="edgar" if i % 3 == 0 else "rss", signals=["offering_priced"] if i % 3 == 0 else None,
                severity=2 if i % 3 == 0 else None)
        s.commit()
    start = time.perf_counter()
    g = graph(GraphParams(days=7, max_nodes=400))
    elapsed = time.perf_counter() - start
    assert len(g["nodes"]) == 400
    assert len(g["edges"]) <= 8 * 400
    assert len([c for c in g["clusters"] if c["id"] != -1]) >= 6
    assert elapsed < 5.0, f"400-node graph took {elapsed:.2f}s"


def test_no_heavy_deps_no_app_main_no_causal_wording():
    for p in PACKAGE.glob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(numpy|sklearn|scipy|networkx|pandas)\b", src, re.M), p.name
        assert not re.search(r"^\s*(import\s+app\.main|from\s+app\.main\s+import|from\s+app\s+import\s+main)\b", src, re.M), p.name
        assert not re.search(r"\bcausal", src, re.I), p.name
    assert (PACKAGE / "AGENTS.md").exists()
