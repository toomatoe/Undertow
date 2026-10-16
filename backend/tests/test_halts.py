from datetime import datetime, timezone

import httpx

from app.alerts.service import store_halts
from app.config import Settings
from app.db import Base, SessionLocal, engine
from app.fundamentals.service import short_summary
from app.models import Company, TradingHalt, WatchlistItem
from app.sources.halts import parse_feed

ITEM = """<item><title>{sym}</title>
<ndaq:HaltDate>10/16/2026</ndaq:HaltDate><ndaq:HaltTime>{t}.440</ndaq:HaltTime>
<ndaq:IssueSymbol>{sym}</ndaq:IssueSymbol><ndaq:IssueName>{sym} Corp</ndaq:IssueName>
<ndaq:Market>NASDAQ</ndaq:Market><ndaq:ReasonCode>{code}</ndaq:ReasonCode><ndaq:PauseThresholdPrice />
<ndaq:ResumptionDate>{rd}</ndaq:ResumptionDate><ndaq:ResumptionQuoteTime>{rq}</ndaq:ResumptionQuoteTime>
<ndaq:ResumptionTradeTime>{rt}</ndaq:ResumptionTradeTime></item>"""


def feed(*items):
    return "<rss><channel>" + "".join(ITEM.format(**i) for i in items) + "</channel></rss>"


def item(sym="TINY", t="14:06:48", code="T1", rd="", rq="", rt=""):
    return dict(sym=sym, t=t, code=code, rd=rd, rq=rq, rt=rt)


NOW = datetime(2026, 10, 16, 18, 10, tzinfo=timezone.utc)  # 14:10 ET


class FakePost:
    def __init__(self):
        self.calls = []

    def __call__(self, url, json, timeout):
        self.calls.append(json)
        return httpx.Response(204, request=httpx.Request("POST", url))


def settings():
    return Settings(database_url="sqlite:///:memory:", discord_webhook_url="https://discord.test/x",
                    alert_sizes=["nano", "micro", "small"], alert_max_age_minutes=15)


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([Company(symbol="TINY", cik=1, name="Tiny", size_bucket="nano", public_float=2e7),
                   Company(symbol="BIG", cik=2, name="Big", size_bucket="large", public_float=5e10)])
        s.commit()


def test_parse_feed():
    halts = parse_feed(feed(item(code="LUDP", rd="10/16/2026", rq="14:11:48", rt="14:11:50")))
    h = halts[0]
    assert (h.symbol, h.reason_code, h.reason) == ("TINY", "LUDP", "Volatility pause (limit up/limit down)")
    assert h.halted_at.astimezone(timezone.utc) == datetime(2026, 10, 16, 18, 6, 48, tzinfo=timezone.utc)
    assert h.resumed_at.strftime("%H:%M:%S") == "14:11:50" and not h.serious


def test_store_dedupes_updates_resumption_and_stores_utc():
    post = FakePost()
    with SessionLocal() as s:
        res = store_halts(s, parse_feed(feed(item(), item())), settings(), post=post, now=NOW)
        assert res["new"] == 1
        store_halts(s, parse_feed(feed(item(rd="10/16/2026", rt="15:00:00"))), settings(), post=post, now=NOW)
        row = s.query(TradingHalt).one()
        assert row.resumed_at is not None
        stored = row.halted_at if row.halted_at.tzinfo else row.halted_at.replace(tzinfo=timezone.utc)
        assert stored == datetime(2026, 10, 16, 18, 6, 48, tzinfo=timezone.utc)


def test_halt_alert_rules():
    post = FakePost()
    with SessionLocal() as s:
        s.add(WatchlistItem(symbol="BIG"))
        s.commit()
        halts = parse_feed(feed(
            item("TINY", "14:06:48", "T1"),    # news-pending halt on a nano cap -> alert
            item("TINY", "14:07:00", "LUDP"),  # volatility pause on a non-watchlist name -> no alert
            item("BIG", "14:08:00", "LUDP"),   # volatility pause, but on the watchlist -> alert
            item("TINY", "13:00:00", "T1"),    # older than 15 minutes -> no alert
        ))
        res = store_halts(s, halts, settings(), post=post, now=NOW)
    assert res == {"seen": 4, "new": 4, "alerted": 2}
    titles = [c["embeds"][0]["title"] for c in post.calls]
    assert titles[0].startswith("⏸️ $TINY halted · News pending") and "$BIG" in titles[1]


def test_short_summary():
    series = [{"date": "2026-09-15", "shares_short": 90, "days_to_cover": 5.0, "change_pct": 1.0, "avg_daily_volume": 18},
              {"date": "2026-09-30", "shares_short": 100, "days_to_cover": 6.0, "change_pct": 11.1, "avg_daily_volume": 17}]
    s = short_summary(series, 400)
    assert s["shares_short"] == 100 and s["pct_of_shares_outstanding"] == 0.25 and len(s["history"]) == 2
    assert short_summary([], 400) is None
