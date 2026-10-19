"""Hypothetical paper portfolio (app/paper/service.py): synthetic journal rows + stub price series, no network."""

import json
import pathlib
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main
from app.backtest.engine import TRADING_DAYS, StrategyConfig
from app.db import Base, SessionLocal, engine
from app.models import JournalEntry
from app.paper import service as paper
from app.research.eventstudy import BORROW_APR, COSTS
from app.research.prices import PriceSeries

START = date(2026, 3, 2)  # Monday
DAYS = [START + timedelta(days=i) for i in range(90) if (START + timedelta(days=i)).weekday() < 5]
TODAY = DAYS[-1]
client = TestClient(main.app)  # no `with`: skip the lifespan


def series(sym, closes, days=DAYS):
    n = len(closes)
    return PriceSeries(sym, days[:n], list(closes), list(closes), [1e6] * n)


FLAT = [100.0] * len(DAYS)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    main.state.paper_cache = {}
    yield


_ids = iter(range(1, 10_000))


def add(ticker, signal="offering_priced", direction="-", bucket="nano", entry_i=0, status="complete",
        borrow_fee=None):
    with SessionLocal() as s:
        aid = next(_ids)
        s.add(JournalEntry(
            article_id=aid, ticker=ticker, signals=[signal], primary_signal=signal, direction=direction,
            severity=2, size_bucket=bucket, filed_at=datetime(2026, 3, 1, 15, tzinfo=timezone.utc),
            status=status, entry_date=DAYS[entry_i] if entry_i is not None else None,
            entry_price=10.0 if entry_i is not None else None, borrow_fee=borrow_fee,
        ))
        s.commit()


def run(prices, **kw):
    kw.setdefault("today", TODAY)
    with SessionLocal() as s:
        return paper.build_portfolio(s, "/nonexistent", price_loader=lambda t: prices.get(t), **kw)


def ramp(start, step, n=len(DAYS)):
    return [start + step * k for k in range(n)]


def test_long_and_short_pnl_with_costs_and_borrow():
    add("LNG", signal="activist_stake", direction="+", bucket="micro")
    add("SHT", signal="offering_priced", direction="-", bucket="nano")
    add("FEE", signal="offering_priced", direction="-", bucket="nano", borrow_fee=0.10)
    prices = {"IWM": series("IWM", FLAT), "LNG": series("LNG", ramp(10, 0.1)),
              "SHT": series("SHT", ramp(10, -0.1)), "FEE": series("FEE", ramp(10, -0.1))}
    out = run(prices, notional=10_000, max_concurrent=10)
    by = {p["ticker"]: p for p in out["positions"]}
    # 20 trading days: price 10 -> 12 (long) / 10 -> 8 (short)
    assert by["LNG"]["side"] == "long" and by["LNG"]["exit_date"] == DAYS[20].isoformat()
    assert by["LNG"]["net_return"] == pytest.approx(0.2 - COSTS["micro"], abs=1e-5)
    assert by["SHT"]["side"] == "short"
    assert by["SHT"]["net_return"] == pytest.approx(0.2 - COSTS["nano"] - BORROW_APR["nano"] * 20 / TRADING_DAYS, abs=1e-5)
    # recorded IBKR fee wins over the bucket APR
    assert by["FEE"]["net_return"] == pytest.approx(0.2 - COSTS["nano"] - 0.10 * 20 / TRADING_DAYS, abs=1e-5)
    t = out["totals"]
    assert t["n_closed"] == 3 and t["n_open"] == 0 and t["hit_rate"] == 1.0
    assert t["pnl"] == pytest.approx(sum(p["pnl"] for p in out["positions"]), abs=0.05)
    assert t["return_pct"] == pytest.approx(t["pnl"] / 100_000, abs=1e-5)
    assert out["equity_curve"][-1]["equity"] == pytest.approx(100_000 + t["pnl"], abs=0.05)
    assert out["equity_curve"][0]["open_positions"] == 3 and out["equity_curve"][-1]["open_positions"] == 0
    assert out["empty_reason"] is None and out["label"] == paper.LABEL


def test_insider_cluster_purchase_uses_5_day_horizon_others_20():
    add("INS", signal="insider_cluster_purchase", direction="+", bucket="micro")
    add("ACT", signal="activist_stake", direction="+", bucket="micro")
    prices = {"IWM": series("IWM", FLAT), "INS": series("INS", ramp(10, 0.1)), "ACT": series("ACT", ramp(10, 0.1))}
    out = run(prices)
    by = {p["ticker"]: p for p in out["positions"]}
    assert by["INS"]["horizon"] == 5 and by["INS"]["exit_date"] == DAYS[5].isoformat()
    assert by["INS"]["net_return"] == pytest.approx(0.05 - COSTS["micro"], abs=1e-5)
    assert by["ACT"]["horizon"] == 20 and by["ACT"]["exit_date"] == DAYS[20].isoformat()
    sig = {r["signal"]: r for r in out["by_signal"]}
    assert sig["insider_cluster_purchase"]["forward_test"] is True
    assert sig["insider_cluster_purchase"]["forward_test_label"]
    assert sig["activist_stake"]["forward_test"] is False and sig["activist_stake"]["horizon"] == 20


def test_open_position_marked_with_half_cost():
    add("OPN", signal="activist_stake", direction="+", bucket="small", entry_i=len(DAYS) - 6, status="open")
    prices = {"IWM": series("IWM", FLAT), "OPN": series("OPN", FLAT)}
    out = run(prices)
    p = out["positions"][0]
    assert p["status"] == "open" and p["exit_date"] is None
    assert p["net_return"] == pytest.approx(-COSTS["small"] / 2, abs=1e-6)
    assert out["totals"]["n_open"] == 1 and out["totals"]["hit_rate"] is None


def test_max_concurrent_skips_new_entries():
    add("A", signal="activist_stake", direction="+", bucket="small", entry_i=0)
    add("B", signal="activist_stake", direction="+", bucket="small", entry_i=1)  # A still open: skipped
    add("C", signal="activist_stake", direction="+", bucket="small", entry_i=20)  # A exits at DAYS[20]: allowed
    prices = {t: series(t, FLAT) for t in ("IWM", "A", "B", "C")}
    out = run(prices, max_concurrent=1)
    assert out["totals"]["skipped_capacity"] == 1
    assert sorted(p["ticker"] for p in out["positions"]) == ["A", "C"]
    assert max(pt["open_positions"] for pt in out["equity_curve"]) == 1


def test_hedge_adds_opposite_iwm_leg():
    add("LNG", signal="activist_stake", direction="+", bucket="micro")
    prices = {"IWM": series("IWM", ramp(100, 0.5)), "LNG": series("LNG", ramp(10, 0.1))}
    plain = run(prices)["positions"][0]["net_return"]
    hedged = run(prices, hedge=True)
    bench_ret = (100 + 0.5 * 20) / 100 - 1
    assert hedged["assumptions"]["hedge"] is True
    assert hedged["positions"][0]["net_return"] == pytest.approx(plain - bench_ret - StrategyConfig().hedge_cost, abs=1e-5)


def test_unpriced_pending_and_undirected_are_counted_not_traded():
    add("HAS", signal="activist_stake", direction="+", bucket="small")
    add("MISSING", signal="activist_stake", direction="+", bucket="small")
    add("WAIT", signal="activist_stake", direction="+", bucket="small", entry_i=None, status="waiting")
    add("NODATA", signal="activist_stake", direction="+", bucket="small", entry_i=None, status="no_data")
    add("EARN", signal="earnings", direction="?", bucket="small")
    prices = {"IWM": series("IWM", FLAT), "HAS": series("HAS", FLAT), "EARN": series("EARN", FLAT)}
    out = run(prices)
    t = out["totals"]
    assert [p["ticker"] for p in out["positions"]] == ["HAS"]
    assert t["unpriced"] == 2 and t["pending"] == 1 and t["undirected"] == 1


def test_short_data_ended_pays_delist_penalty():
    add("DEL", signal="offering_priced", direction="-", bucket="nano", status="data_ended")
    prices = {"IWM": series("IWM", FLAT), "DEL": series("DEL", [10.0] * 8)}
    p = run(prices)["positions"][0]
    assert p["status"] == "closed" and p["exit_date"] == DAYS[7].isoformat()
    expected = -StrategyConfig().delist_penalty - COSTS["nano"] - BORROW_APR["nano"] * 7 / TRADING_DAYS
    assert p["net_return"] == pytest.approx(expected, abs=1e-5)


def test_empty_journal_is_well_formed():
    out = run({})
    assert out["empty_reason"] and out["label"] == paper.LABEL
    assert out["equity_curve"] == [] and out["positions"] == [] and out["by_signal"] == []
    assert out["totals"]["pnl"] == 0 and out["totals"]["n_closed"] == 0
    # young journal: only unpriced rows
    add("WAIT", signal="activist_stake", direction="+", entry_i=None, status="waiting")
    young = run({})
    assert young["empty_reason"] and young["totals"]["pending"] == 1


def _yahoo_payload(days, closes):
    stamps = [int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=timezone.utc).timestamp()) for d in days]
    return {"chart": {"result": [{"timestamp": stamps, "indicators": {
        "adjclose": [{"adjclose": closes}], "quote": [{"close": closes, "volume": [1000] * len(closes)}]}}]}}


def test_endpoint_shape_reads_cache_only(tmp_path, monkeypatch):
    cache = tmp_path / "prices_live"
    cache.mkdir()
    end = TODAY + timedelta(days=1)
    for sym, closes in (("IWM", FLAT), ("LNG", ramp(10, 0.1))):
        (cache / f"{sym}_2026-02-20_{end}.json").write_text(json.dumps(_yahoo_payload(DAYS, closes)))
    # an older, narrower cache file for the same ticker must lose to the newest one
    (cache / "LNG_2026-02-20_2026-03-05.json").write_text(json.dumps(_yahoo_payload(DAYS[:3], [1.0, 1.0, 1.0])))
    add("LNG", signal="activist_stake", direction="+", bucket="micro")

    def no_network(*a, **k):
        raise AssertionError("network call in the request path")

    monkeypatch.setattr("app.research.prices.httpx.get", no_network)
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))

    class FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=tz)

    monkeypatch.setattr(main, "datetime", FixedDT)
    r = client.get("/api/paper-portfolio", params={"hedge": "true", "max_concurrent": 5})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"as_of", "label", "assumptions", "equity_curve", "totals", "by_signal", "positions", "empty_reason"}
    assert "Hypothetical" in body["label"] and "not investment advice" in body["label"]
    assert body["assumptions"]["notional"] == main.PAPER_NOTIONAL and body["assumptions"]["max_concurrent"] == 5
    assert body["totals"]["n_closed"] == 1 and body["positions"][0]["ticker"] == "LNG"
    assert body["equity_curve"] and set(body["equity_curve"][0]) == {"date", "equity", "open_positions"}
    # cached per (date, params)
    assert len(main.state.paper_cache) == 1
    assert client.get("/api/paper-portfolio", params={"hedge": "true", "max_concurrent": 5}).json() == body
    assert client.get("/api/paper-portfolio", params={"max_concurrent": 0}).status_code == 422
    assert client.get("/api/paper-portfolio", params={"max_concurrent": 101}).status_code == 422


def _old_and_new_cache_files(cache, sym, old_closes, new_closes, old_n=31, new_from=40):
    """Mimic journal.service.mark(): an old file written while an old entry was open, and today's file whose
    start moved forward past that entry once it completed."""
    old_end = DAYS[old_n - 1] + timedelta(days=1)
    (cache / f"{sym}_2026-02-20_{old_end}.json").write_text(
        json.dumps(_yahoo_payload(DAYS[:old_n], old_closes[:old_n])))
    new_start = DAYS[new_from] - timedelta(days=1)
    (cache / f"{sym}_{new_start}_{TODAY + timedelta(days=1)}.json").write_text(
        json.dumps(_yahoo_payload(DAYS[new_from:], new_closes[new_from:])))


def _run_cached(data_dir, **kw):
    with SessionLocal() as s:
        return paper.build_portfolio(s, str(data_dir), today=TODAY, **kw)


def test_old_entry_priced_from_older_cache_file(tmp_path, monkeypatch):
    cache = tmp_path / "prices_live"
    cache.mkdir()
    # the newer file is on a different adjusted basis (x2): positions must not mix files
    _old_and_new_cache_files(cache, "TKR", ramp(10, 0.1), [2 * c for c in ramp(10, 0.1)])
    _old_and_new_cache_files(cache, "IWM", FLAT, FLAT)
    add("TKR", signal="activist_stake", direction="+", bucket="micro", entry_i=0)  # completed long ago
    add("TKR", signal="activist_stake", direction="+", bucket="micro", entry_i=len(DAYS) - 6, status="open")
    monkeypatch.setattr("app.research.prices.httpx.get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    out = _run_cached(tmp_path)
    assert out["totals"]["unpriced"] == 0 and len(out["positions"]) == 2
    old = next(p for p in out["positions"] if p["entry_date"] == DAYS[0].isoformat())
    assert old["status"] == "closed" and old["exit_date"] == DAYS[20].isoformat()
    assert old["net_return"] == pytest.approx(0.2 - COSTS["micro"], abs=1e-5)
    new = next(p for p in out["positions"] if p["status"] == "open")
    assert new["net_return"] == pytest.approx((ramp(10, 0.1)[-1] / ramp(10, 0.1)[-6] - 1) - COSTS["micro"] / 2,
                                              abs=1e-5)
    # the curve starts on the old entry's day even though the newest IWM file starts later
    assert out["equity_curve"][0]["date"] == DAYS[0].isoformat()


def test_hedge_uses_older_iwm_file_for_old_entry(tmp_path):
    cache = tmp_path / "prices_live"
    cache.mkdir()
    _old_and_new_cache_files(cache, "TKR", ramp(10, 0.1), ramp(10, 0.1))
    _old_and_new_cache_files(cache, "IWM", ramp(100, 0.5), [3 * c for c in ramp(100, 0.5)])
    add("TKR", signal="activist_stake", direction="+", bucket="micro", entry_i=0)
    out = _run_cached(tmp_path, hedge=True)
    assert out["totals"]["unpriced"] == 0 and out["empty_reason"] is None
    p = out["positions"][0]
    bench_ret = (100 + 0.5 * 20) / 100 - 1
    assert p["net_return"] == pytest.approx(0.2 - COSTS["micro"] - bench_ret - StrategyConfig().hedge_cost, abs=1e-5)
    assert out["equity_curve"][0]["date"] == DAYS[0].isoformat()


def test_endpoint_empty_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(main.settings, "data_dir", str(tmp_path))
    body = client.get("/api/paper-portfolio").json()
    assert body["empty_reason"] and body["label"] == paper.LABEL and body["positions"] == []


def test_paper_package_has_no_execution_code():
    """No order placement, broker or Alpaca code in the paper package (order_by is SQL, allowed)."""
    pkg = pathlib.Path(paper.__file__).parent
    for f in pkg.glob("*.py"):
        text = f.read_text(encoding="utf-8").replace("order_by", "")
        hits = re.findall(r"(?i)order|broker|submit|alpaca", text)
        assert not hits, f"{f.name}: {hits}"
