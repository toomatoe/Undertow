from datetime import date, datetime, timedelta, timezone

import pytest

from app.db import Base, SessionLocal, engine
from app.journal.service import mark_entry, record_new, summary
from app.models import Article, ArticleTicker, Company, JournalEntry
from app.research.prices import PriceSeries

START = date(2026, 3, 2)  # Monday
DAYS = [START + timedelta(days=i) for i in range(60) if (START + timedelta(days=i)).weekday() < 5]


def series(closes):
    n = len(closes)
    return PriceSeries("X", DAYS[:n], list(closes), list(closes), [1e6] * n)


FLAT_BENCH = series([100.0] * len(DAYS))


def entry(filed: datetime) -> JournalEntry:
    return JournalEntry(article_id=1, ticker="X", signals=["offering_priced"], primary_signal="offering_priced",
                        direction="-", severity=2, size_bucket="nano", filed_at=filed, status="waiting")


def et(d: date, hour: int) -> datetime:
    # 14:00 UTC = 10:00 ET in March (EDT starts Mar 8 2026; use UTC-5 before, UTC-4 after - irrelevant at 10:00)
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=timezone.utc)


def test_entry_is_day0_plus_one_and_horizons_fill():
    closes = [10.0] * 3 + [10.0 * 0.99**k for k in range(1, 40)]
    e = entry(et(DAYS[2], 14))  # accepted Wednesday mid-morning ET -> day 0 = Wednesday
    mark_entry(e, series(closes), FLAT_BENCH, DAYS[-1])
    assert e.entry_date == DAYS[3]  # day 0 + 1
    assert e.status == "complete"
    assert e.abn_1 == pytest.approx(0.99 - 1, abs=1e-4)
    assert e.abn_20 == pytest.approx(0.99**20 - 1, abs=1e-4)


def test_after_close_filing_shifts_day0():
    e = entry(datetime(2026, 3, 4, 21, 30, tzinfo=timezone.utc))  # 16:30 ET Wednesday
    mark_entry(e, series([10.0] * 40), FLAT_BENCH, DAYS[-1])
    assert e.entry_date == DAYS[4]  # day 0 = Thursday, entry Friday


def test_waiting_until_prices_exist_then_partial():
    e = entry(et(DAYS[2], 14))
    mark_entry(e, series([10.0] * 3), FLAT_BENCH, DAYS[2])
    assert e.status == "waiting" and e.entry_date is None
    mark_entry(e, series([10.0] * 6), FLAT_BENCH, DAYS[5])
    assert e.status == "open" and e.abn_1 == 0 and e.abn_5 is None


def test_data_ended_and_no_data():
    e = entry(et(DAYS[2], 14))
    mark_entry(e, series([10.0] * 9), FLAT_BENCH, DAYS[8] + timedelta(days=30))
    assert e.status == "data_ended" and e.abn_5 is not None and e.abn_20 is None
    e2 = entry(et(DAYS[2], 14))
    mark_entry(e2, None, FLAT_BENCH, DAYS[2] + timedelta(days=30))
    assert e2.status == "no_data"


def test_record_new_and_summary(tmp_path):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add(Company(symbol="TINY", cik=1, name="Tiny", public_float=20_000_000, size_bucket="nano"))
        s.add(Article(url="u1", url_hash="u1", title_hash="t1", title="424B5: Tiny", source="edgar", source_name="SEC",
                      published_at=datetime(2026, 3, 4, 14, tzinfo=timezone.utc), form="424B5",
                      signals=["offering_priced"], severity=2, tickers=[ArticleTicker(symbol="TINY", method="edgar")]))
        s.add(Article(url="u2", url_hash="u2", title_hash="t2", title="8-K: Unknown", source="edgar", source_name="SEC",
                      published_at=datetime(2026, 3, 4, 14, tzinfo=timezone.utc), form="8-K",
                      signals=["auditor_change"], severity=2, tickers=[ArticleTicker(symbol="NOSIZE", method="edgar")]))
        s.commit()
        assert record_new(s, str(tmp_path)) == 1  # the unsized ticker is skipped
        assert record_new(s, str(tmp_path)) == 0  # idempotent
        e = s.query(JournalEntry).one()
        assert (e.ticker, e.size_bucket, e.primary_signal, e.direction) == ("TINY", "nano", "offering_priced", "-")
        e.abn_5, e.abn_20 = -0.10, -0.20
        s.commit()
        rows = summary(s, {("offering_priced", "nano", 20): {"mean_abnormal": -0.156}})
        assert rows[0]["n"] == 1 and rows[0]["hit_20"] == 1.0 and rows[0]["expected_20"] == -0.156
