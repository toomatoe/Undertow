from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app, state
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
