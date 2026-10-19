import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import AdminSettings
from app.db import Base, SessionLocal, engine
from app.journal import digest as chain
from app.main import app, state
from app.research_jobs import MODULES
from app.models import Article, ArticleTicker, Company
from app.schemas import Evidence

# No `with TestClient(...)`: skip the lifespan, which loads SEC data over the network
client = TestClient(app)


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with SessionLocal() as s:
        s.add_all(
            [
                Company(symbol="TINY", cik=1, name="Tiny Corp", public_float=30_000_000, size_bucket="nano"),
                Company(symbol="BIG", cik=2, name="Big Corp", public_float=50_000_000_000, size_bucket="large"),
            ]
        )
        for i, (sym, sigs, sev) in enumerate([("TINY", ["auditor_change"], 2), ("BIG", ["earnings"], 1), ("TINY", None, None)]):
            s.add(
                Article(
                    url=f"https://sec.gov/{i}", url_hash=f"h{i}", title_hash=f"t{i}", title=f"Filing {i}",
                    source="edgar", source_name="SEC EDGAR", published_at=now, form="8-K",
                    signals=sigs, severity=sev, tickers=[ArticleTicker(symbol=sym, method="edgar")],
                )
            )
        s.commit()
    state.sizes = {"TINY": "nano", "BIG": "large"}
    state.evidence = {
        ("auditor_change", "nano"): Evidence(
            signal="auditor_change", bucket="nano", n=30, horizon_days=20, mean_abnormal=-0.08,
            mean_net=0.05, t_stat=-3.1, significant=True,
        )
    }


def test_signals_default_to_small_caps_with_evidence():
    items = client.get("/api/signals").json()["items"]
    assert [a["title"] for a in items] == ["Filing 0"]
    a = items[0]
    assert a["signals"][0]["code"] == "auditor_change"
    assert a["tickers"][0]["size_bucket"] == "nano"
    assert a["evidence"][0]["mean_abnormal"] == -0.08


def test_signals_all_sizes_and_signal_filter():
    assert len(client.get("/api/signals?size=").json()["items"]) == 2
    items = client.get("/api/signals?size=&signal=earnings").json()["items"]
    assert [a["title"] for a in items] == ["Filing 1"]
    assert client.get("/api/signals?size=huge").status_code == 422


def test_articles_size_filter():
    titles = {a["title"] for a in client.get("/api/articles?size=nano").json()["items"]}
    assert titles == {"Filing 0", "Filing 2"}


def test_watchlist_roundtrip():
    assert client.put("/api/watchlist/big").json()["on_watchlist"] is True
    assert [w["symbol"] for w in client.get("/api/watchlist").json()] == ["BIG"]
    items = client.get("/api/signals?size=&watchlist=true").json()["items"]
    assert [a["title"] for a in items] == ["Filing 1"]
    client.delete("/api/watchlist/BIG")
    assert client.get("/api/watchlist").json() == []


def test_ticker_sitemap_routed_before_symbol_detail():
    paths = [getattr(r, "path", None) for r in app.routes]
    assert paths.index("/api/tickers/sitemap") < paths.index("/api/tickers/{symbol}")
    r = client.get("/api/tickers/sitemap")
    assert r.status_code == 200 and isinstance(r.json(), list)  # not ticker_detail("SITEMAP")


def test_ticker_sitemap_fields_company_filter_and_days():
    now = datetime.now(timezone.utc)
    sizes = dict(state.sizes)
    with SessionLocal() as s:
        s.add(Company(symbol="OLDS", cik=3, name="Old Small Co", public_float=900_000_000, size_bucket="small"))
        for i, (sym, age) in enumerate([("OLDS", 40), ("ORPH", 1)]):  # ORPH has no Company row
            s.add(Article(url=f"https://news/sm{i}", url_hash=f"sm{i}", title_hash=f"sm{i}", title=f"Sitemap {i}", source="rss",
                          source_name="X", published_at=now - timedelta(days=age), tickers=[ArticleTicker(symbol=sym, method="cashtag")]))
        s.commit()
    state.sizes = {**sizes, "OLDS": "small"}
    try:
        rows = client.get("/api/tickers/sitemap").json()
        by = {r["symbol"]: r for r in rows}
        assert set(by) == {"TINY", "BIG", "OLDS"}  # ORPH excluded: no Company
        assert set(by["TINY"]) == {"symbol", "last_activity", "items", "size_bucket"}
        assert by["TINY"]["items"] == 2 and by["TINY"]["size_bucket"] == "nano" and by["BIG"]["items"] == 1
        last = datetime.fromisoformat(by["TINY"]["last_activity"])
        assert last.utcoffset() == timedelta(0) and abs((last - now).total_seconds()) < 3600
        assert rows[-1]["symbol"] == "OLDS"  # most recent activity first
        assert {r["symbol"] for r in client.get("/api/tickers/sitemap?days=30").json()} == {"TINY", "BIG"}
        assert client.get("/api/tickers/sitemap?days=0").status_code == 422
    finally:
        state.sizes = sizes
        with SessionLocal() as s:
            for a in s.query(Article).filter(Article.url_hash.in_(["sm0", "sm1"])).all():
                s.delete(a)
            s.query(Company).filter(Company.symbol == "OLDS").delete()
            s.commit()


# --- Studies (fixed allowlist) -------------------------------------------------------------------


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_study_allowlist(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(state, "study_cache", {})
    main_study = {"generated_at": "2026-10-01T00:00:00+00:00", "config": {"study": "in_sample"}, "testing": {"n_tests": 40}, "results": []}
    monkeypatch.setattr(state, "study", main_study)
    # main: default and explicit give the unchanged in-memory study
    assert client.get("/api/research/event-study").json() == main_study
    assert client.get("/api/research/event-study?study=main").json() == main_study
    # oos present, insider missing
    oos = {"generated_at": "2026-10-19T00:00:00+00:00", "config": {"study": "oos"}, "testing": {"n_tests": 12},
           "results": [], "confirmatory": [{"id": "H1", "verdict": "underpowered"}]}
    write_json(tmp_path / "event_study_oos.json", oos)
    assert client.get("/api/research/event-study?study=oos").json() == oos
    r = client.get("/api/research/event-study?study=insider_purchases")
    assert r.status_code == 404 and "insider" in r.json()["detail"]
    for bad in ["../event_study", "..%2F..%2Fetc%2Fpasswd", "event_study_oos.json", "OOS", "", "main/../oos"]:
        assert client.get(f"/api/research/event-study?study={bad}").status_code == 422, bad
    write_json(tmp_path / "event_study_main_shadow.json", {"x": 1})  # files off the allowlist are never served
    assert client.get("/api/research/event-study?study=main_shadow").status_code == 422


def test_studies_list(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(state, "study_cache", {})
    write_json(tmp_path / "event_study.json", {"generated_at": "g1", "config": {"study": "in_sample"}, "testing": {"n_tests": 40}, "results": []})
    write_json(tmp_path / "event_study_oos.json", {"generated_at": "g2", "config": {"study": "oos"}, "testing": {"n_tests": 12}, "results": []})
    (tmp_path / "event_study_insider_purchases.json").write_text("{not json", encoding="utf-8")
    rows = {r["study"]: r for r in client.get("/api/research/studies").json()}
    assert list(rows) == ["main", "oos", "insider_purchases"]
    assert rows["main"] == {"study": "main", "available": True, "generated_at": "g1", "n_tests": 40, "design": "in_sample"}
    assert rows["oos"]["n_tests"] == 12 and rows["oos"]["design"] == "oos"
    assert rows["insider_purchases"]["available"] is False  # unreadable file: reported, not a 500


# --- Research kinds ---------------------------------------------------------------------------


class StubJobs:
    def __init__(self):
        self.started = []

    def start(self, kind):
        self.started.append(kind)
        return {"id": f"id-{kind}", "kind": kind, "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None, "message": "running"}

    def snapshot(self):
        return {"active": None, "latest": dict.fromkeys(MODULES)}


def test_research_kinds_come_from_modules(monkeypatch):
    stub = StubJobs()
    monkeypatch.setattr(main, "research_jobs", stub)
    monkeypatch.setattr(main, "research_launch", AdminSettings(_env_file=None))
    monkeypatch.setattr(main.settings, "public_base_url", "http://localhost:3000")
    for kind in MODULES:
        r = client.post(f"/api/research/jobs/{kind}")
        assert r.status_code == 202 and r.json()["kind"] == kind
    assert stub.started == list(MODULES)
    assert {"event_study_oos", "insider_study"} <= set(stub.started)
    assert client.post("/api/research/jobs/app.research.oos").status_code == 422
    assert client.post("/api/research/jobs/" + "x" * 100).status_code == 422
    assert set(client.get("/api/research/jobs").json()["latest"]) == set(MODULES)


# --- Journal hash chain -------------------------------------------------------------------------


def seal_empty_days(data_dir, days):
    """Hand-made chain for days without journal entries (the test DB has none)."""
    prev = chain.GENESIS
    lines = []
    for d in days:
        h = chain.day_hash([], prev, d)
        lines.append({"day": d.isoformat(), "prev_hash": prev, "hash": h, "count": 0, "sealed_at": "2026-10-19T00:05:00Z", "sealed_late": False})
        prev = h
    (data_dir / chain.CHAIN_FILE).write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in lines), encoding="utf-8")
    return lines


def test_chain_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(state, "verify_cache", None)
    assert client.get("/api/journal/chain").json() == {"head": None, "lines": [], "error": None}

    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(35)]
    lines = seal_empty_days(tmp_path, days)
    body = client.get("/api/journal/chain").json()
    assert body["head"] == {"head_hash": lines[-1]["hash"], "head_day": "2026-09-04", "days": 35}
    assert len(body["lines"]) == 30 and body["lines"][-1]["hash"] == lines[-1]["hash"] and body["lines"][0]["day"] == "2026-08-06"

    day = client.get("/api/journal/chain/2026-08-02").json()
    assert day == {"day": "2026-08-02", "prev_hash": lines[0]["hash"], "hash": lines[1]["hash"], "entries": []}
    assert client.get("/api/journal/chain/2026-10-01").status_code == 404  # not sealed
    for bad in ["2026-13-01", "2026-02-30", "yesterday", "2026-8-1"]:
        assert client.get(f"/api/journal/chain/{bad}").status_code == 422, bad

    v = client.get("/api/journal/verify").json()
    assert v["ok"] is True and v["days"] == 35 and v["head_hash"] == lines[-1]["hash"] and v["checked_at"]

    # Tamper with one stored hash: the cached result is served for 10 minutes, then the break shows
    tampered = [{**x, "hash": "f" * 64} if i == 3 else x for i, x in enumerate(lines)]
    (tmp_path / chain.CHAIN_FILE).write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in tampered), encoding="utf-8")
    assert client.get("/api/journal/verify").json()["ok"] is True
    cached_at, result = state.verify_cache
    monkeypatch.setattr(state, "verify_cache", (cached_at - main.VERIFY_TTL_SECONDS - 1, result))
    broken = client.get("/api/journal/verify").json()
    assert broken["ok"] is False and broken["first_mismatch"]["day"] == "2026-08-04"


def test_chain_reports_malformed_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    lines = seal_empty_days(tmp_path, [date(2026, 8, 1), date(2026, 8, 2)])
    with open(tmp_path / chain.CHAIN_FILE, "a", encoding="utf-8") as f:
        f.write("garbage\n")
    body = client.get("/api/journal/chain").json()
    assert body["head"] is None and body["error"] == "line 3 is malformed" and len(body["lines"]) == len(lines)


def test_seal_cycle_runs_once_per_day(monkeypatch):
    monkeypatch.setattr(state, "sealed_through", None)
    calls = []

    def fake_seal(session, data_dir, through, now=None):
        calls.append(through)
        return [{"day": through.isoformat()}]

    monkeypatch.setattr(main.chain, "seal_through", fake_seal)
    monkeypatch.setattr(state, "verify_cache", (0.0, {"ok": True}))
    now = datetime(2026, 10, 19, 0, 10, tzinfo=timezone.utc)
    main.seal_cycle(now)
    main.seal_cycle(now + timedelta(hours=5))
    assert calls == [date(2026, 10, 18)]  # yesterday UTC, once
    assert state.verify_cache is None  # a new seal invalidates the cached verification
    main.seal_cycle(now + timedelta(days=1))
    assert calls[-1] == date(2026, 10, 19)


# --- Delivery wiring ----------------------------------------------------------------------------


def test_purge_cycle_runs_once_per_utc_day_and_retries_after_failure(monkeypatch):
    monkeypatch.setattr(state, "last_purge_day", None)
    calls = []

    def fake_purge(session, now=None):
        calls.append(now)
        return 2

    monkeypatch.setattr(main.delivery, "purge_pending", fake_purge)
    now = datetime(2026, 10, 19, 0, 10, tzinfo=timezone.utc)
    main.purge_cycle(now)
    main.purge_cycle(now + timedelta(hours=20))  # same UTC day: skipped
    assert calls == [now] and state.last_purge_day == date(2026, 10, 19)

    def boom(session, now=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(main.delivery, "purge_pending", boom)
    with pytest.raises(RuntimeError):  # the scheduler catches and logs this; the day stays unpurged
        main.purge_cycle(now + timedelta(days=1))
    assert state.last_purge_day == date(2026, 10, 19)
    monkeypatch.setattr(main.delivery, "purge_pending", fake_purge)
    main.purge_cycle(now + timedelta(days=1, hours=1))  # retried on the next cycle
    assert len(calls) == 2 and state.last_purge_day == date(2026, 10, 20)


def test_purge_cycle_deletes_only_stale_pending_rows(monkeypatch):
    from app.models import Subscriber

    monkeypatch.setattr(state, "last_purge_day", None)
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    with SessionLocal() as s:
        s.add_all([
            Subscriber(email="old-pending@example.com", status="pending", created_at=now - timedelta(days=31)),
            Subscriber(email="new-pending@example.com", status="pending", created_at=now - timedelta(days=2)),
            Subscriber(email="old-active@example.com", status="active", created_at=now - timedelta(days=90)),
        ])
        s.commit()
    try:
        main.purge_cycle(now)
        with SessionLocal() as s:
            left = {e for (e,) in s.query(Subscriber.email).filter(Subscriber.email.like("%@example.com"))}
        assert {"new-pending@example.com", "old-active@example.com"} <= left
        assert "old-pending@example.com" not in left
    finally:
        with SessionLocal() as s:
            s.query(Subscriber).filter(Subscriber.email.in_(["new-pending@example.com", "old-active@example.com"])).delete()
            s.commit()


def test_delivery_router_mounted_and_disabled(monkeypatch):
    for name in ("SMTP_HOST", "EMAIL_FROM", "EMAIL_POSTAL_ADDRESS"):
        monkeypatch.delenv(name, raising=False)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert {"/api/subscribe", "/api/unsubscribe", "/api/delivery/status"} <= paths
    r = client.post("/api/subscribe", json={"email": "reader@example.com", "daily": True})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]
    assert client.get("/api/delivery/status").json() == {"enabled": False}


def test_newsletter_and_digest_sends_are_gated_and_never_crash(monkeypatch):
    sent = []
    monkeypatch.setattr(main.newsletter, "ensure_latest", lambda *a, **k: "2026-W42")
    monkeypatch.setattr(main.delivery, "send_newsletter", lambda s, d, issue: sent.append(("newsletter", issue)) or {})
    monkeypatch.setattr(main.delivery, "daily_digest_day", lambda now=None: date(2026, 10, 18))
    monkeypatch.setattr(state, "last_digest_day", None)

    monkeypatch.setattr(main, "get_delivery_settings", lambda: SimpleNamespace(enabled=False))
    main.newsletter_cycle()
    main.digest_cycle()
    assert sent == []

    monkeypatch.setattr(main, "get_delivery_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(main.delivery, "send_daily_digest", lambda s, d, day: sent.append(("digest", day)) or {})
    main.newsletter_cycle()
    main.digest_cycle()
    main.digest_cycle()  # once per ET day
    assert sent == [("newsletter", "2026-W42"), ("digest", date(2026, 10, 18))]

    def boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr(main.delivery, "send_newsletter", boom)
    monkeypatch.setattr(main.delivery, "send_daily_digest", boom)
    monkeypatch.setattr(main.delivery, "daily_digest_day", lambda now=None: date(2026, 10, 19))
    main.newsletter_cycle()  # logged, not raised
    main.digest_cycle()
    assert state.last_digest_day == date(2026, 10, 18)  # the failed day is retried next cycle
    monkeypatch.setattr(main.delivery, "daily_digest_day", lambda now=None: None)  # before the send hour
    main.digest_cycle()


def test_forward_test_signal_on_api_with_insider_evidence(tmp_path, monkeypatch):
    """insider_cluster_purchase articles show on /api/signals with the insider study's micro / 5d row (bundled copy
    when DATA_DIR has no insider study); the catalog lists it after the main signals with forward_test: true."""
    from app.pipeline.signals import ALL_SIGNALS

    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(state, "forward_evidence", None)
    monkeypatch.setattr(state, "sizes", {**state.sizes, "MICR": "micro"})
    with SessionLocal() as s:
        s.add(Company(symbol="MICR", cik=3, name="Micro Corp", public_float=150_000_000, size_bucket="micro"))
        s.add(Article(url="https://www.sec.gov/Archives/edgar/data/3/x/x-index.htm", url_hash="hins", title_hash="tins",
                      title="Insider cluster purchase: MICR (2 insiders, $40,000 total)", source="edgar",
                      source_name="SEC EDGAR", published_at=datetime.now(timezone.utc), form="4",
                      signals=["insider_cluster_purchase"], severity=2, tickers=[ArticleTicker(symbol="MICR", method="edgar")]))
        s.commit()
    [a] = client.get("/api/signals?signal=insider_cluster_purchase").json()["items"]
    assert a["forward_test"] is True
    assert a["signals"][0]["code"] == "insider_cluster_purchase" and a["signals"][0]["forward_test"] is True
    [ev] = a["evidence"]
    assert (ev["study"], ev["forward_test"], ev["bucket"], ev["horizon_days"]) == ("insider_purchases", True, "micro", 5)
    assert (ev["n"], ev["excess_vs_baseline"], ev["t_stat_clustered"]) == (662, 0.01662, 3.29)
    # main-study evidence keeps its shape, with the optional fields at their defaults
    tiny = next(x for x in client.get("/api/signals").json()["items"] if x["title"] == "Filing 0")
    assert tiny["forward_test"] is False and tiny["evidence"][0]["study"] is None and tiny["evidence"][0]["forward_test"] is False

    catalog = client.get("/api/signals/catalog").json()
    assert [c["code"] for c in catalog][-1] == "insider_cluster_purchase" and catalog[-1]["forward_test"] is True
    assert len(catalog) == len(ALL_SIGNALS) + 1 and not any(c["forward_test"] for c in catalog[:-1])
