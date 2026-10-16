from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from app.alerts.service import Alerter, format_message
from app.config import Settings
from app.db import Base, SessionLocal, engine
from app.models import AlertLog, Article, ArticleTicker, Company, WatchlistItem

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
EV = [{"signal": "offering_priced", "bucket": "nano", "n": 302, "horizon_days": 20, "mean_abnormal": -0.156,
       "mean_net": 0.087, "excess_vs_baseline": -0.137, "t_stat": -6.7, "significant": True}]


def settings(**kw):
    base = dict(database_url="sqlite:///:memory:", discord_webhook_url="https://discord.test/hook",
                alert_min_severity=2, alert_sizes=["nano", "micro", "small"], alert_max_age_minutes=15)
    return Settings(**(base | kw))


class FakePost:
    def __init__(self, status=204, raise_exc=None):
        self.calls, self.status, self.raise_exc = [], status, raise_exc

    def __call__(self, url, json, timeout):
        self.calls.append((url, json))
        if self.raise_exc:
            raise self.raise_exc
        return httpx.Response(self.status, request=httpx.Request("POST", url))


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([
            Company(symbol="TINY", cik=1, name="Tiny", public_float=20_000_000, size_bucket="nano"),
            Company(symbol="BIG", cik=2, name="Big", public_float=50_000_000_000, size_bucket="large"),
        ])
        s.commit()


def add_filing(symbol="TINY", minutes_ago=1, severity=2, signals=("offering_priced",)) -> int:
    with SessionLocal() as s:
        a = Article(url=f"https://sec.gov/{symbol}{minutes_ago}{severity}", url_hash=f"{symbol}{minutes_ago}{severity}",
                    title_hash=f"t{symbol}{minutes_ago}{severity}", title=f"424B5: {symbol} Corp", source="edgar",
                    source_name="SEC EDGAR", published_at=NOW - timedelta(minutes=minutes_ago), form="424B5",
                    signals=list(signals), severity=severity, tickers=[ArticleTicker(symbol=symbol, method="edgar")])
        s.add(a)
        s.commit()
        return a.id


def handle(alerter, article_id):
    with SessionLocal() as s:
        return alerter.handle(s, article_id, now=NOW)


def test_sends_small_cap_signal_with_evidence_and_latency():
    post = FakePost()
    entry = handle(Alerter(settings(), lambda a: EV, post=post), add_filing())
    assert entry.status == "sent" and entry.latency_seconds == 60.0
    payload = post.calls[0][1]["embeds"][0]
    assert payload["title"].startswith("$TINY · 424B5 · Offering priced")
    assert "-15.6% vs index over 20d" in payload["description"]
    assert "not investment advice" in payload["footer"]["text"]
    text = str(payload).lower()
    assert "buy" not in text and "sell" not in text.replace("selling", "")  # impersonal: no calls to action


def test_skip_rules():
    post = FakePost()
    alerter = Alerter(settings(), lambda a: [], post=post)
    assert handle(alerter, add_filing("BIG")).reason == "outside_size_filter"
    assert handle(alerter, add_filing(minutes_ago=30)).reason == "too_old"
    assert handle(alerter, add_filing(severity=1, signals=("earnings",))).reason == "below_severity"
    assert post.calls == []


def test_watchlist_overrides_size_filter():
    with SessionLocal() as s:
        s.add(WatchlistItem(symbol="BIG"))
        s.commit()
    assert handle(Alerter(settings(), lambda a: [], post=FakePost()), add_filing("BIG")).status == "sent"


def test_no_channel_and_delivery_failure_are_logged_not_raised():
    entry = handle(Alerter(settings(discord_webhook_url=None), lambda a: [], post=FakePost()), add_filing())
    assert (entry.status, entry.reason) == ("skipped", "no_channel_configured")
    entry = handle(Alerter(settings(), lambda a: [], post=FakePost(raise_exc=httpx.ConnectError("down"))), add_filing(minutes_ago=2))
    assert (entry.status, entry.reason) == ("failed", "ConnectError")
    with SessionLocal() as s:
        assert s.query(AlertLog).count() == 2


def test_news_articles_are_ignored():
    with SessionLocal() as s:
        a = Article(url="n", url_hash="n", title_hash="n", title="News", source="rss", source_name="CNBC", published_at=NOW)
        s.add(a)
        s.commit()
        assert Alerter(settings(), lambda a: [], post=FakePost()).handle(s, a.id, now=NOW) is None


def test_format_message_without_company():
    a = SimpleNamespace(signals=["auditor_change"], tickers=[], form="8-K", title="8-K: X", url="u", published_at=NOW)
    msg = format_message(a, None, [], 5)
    assert msg["embeds"][0]["fields"][1]["value"] == "size unknown"
