"""Forward signal journal: a live, timestamped track record of every filing signal.

1. `record_new()` (every ingest cycle): one append-only entry per signal-bearing
   filing whose ticker has a known size bucket. Captures today's IBKR borrow if
   the latest snapshot is fresh.
2. `mark()` (at most daily): fills the entry price at the same moment the
   backtest would trade (day 0 + 1 close; see research.eventstudy.day0_index
   and backtest StrategyConfig.entry_delay), then abnormal returns vs IWM at
   +1, +5 and +20 trading days.
3. `summary()`: per signal x size, live results next to what the Edge Lab
   expected, so drift between backtest and reality is visible.

No orders, no money: this is a forward test and a public track record.
"""

import logging
import os
import statistics
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest import borrow
from app.models import Article, Company, JournalEntry
from app.pipeline.signals import ALL_SIGNALS
from app.research.eventstudy import ET, day0_index
from app.research.prices import PriceSeries, load_prices

log = logging.getLogger(__name__)

ENTRY_DELAY = 1  # same as the backtest base case
HORIZONS = (1, 5, 20)
BORROW_MAX_AGE_HOURS = 36
DATA_ENDED_AFTER_DAYS = 10  # calendar days without a print before an open entry is closed out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def recorded_day(entry: JournalEntry) -> date:
    """UTC calendar day the entry was recorded (`created_at`). Naive timestamps (SQLite) are UTC."""
    return _aware(entry.created_at).astimezone(timezone.utc).date()


def entries_recorded_on(session: Session, day: date) -> list[JournalEntry]:
    """Entries whose `created_at` falls on UTC `day`, sorted by id (used by the track-record seal, journal/digest.py).

    The SQL range is widened by a day on each side and the exact UTC day is checked in Python, so the
    result is the same whether the backend stores aware (Postgres) or naive (SQLite) timestamps.
    """
    lo = datetime.combine(day - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(day + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
    rows = session.scalars(
        select(JournalEntry).where(JournalEntry.created_at >= lo, JournalEntry.created_at < hi).order_by(JournalEntry.id)
    ).all()
    return [e for e in rows if recorded_day(e) == day]


def first_recorded_day(session: Session) -> date | None:
    """UTC day of the earliest journal entry, or None when the journal is empty."""
    first = session.scalar(select(func.min(JournalEntry.created_at)))
    return _aware(first).astimezone(timezone.utc).date() if first else None


def record_new(session: Session, data_dir: str) -> int:
    """Create journal entries for signal filings not yet journaled. Returns how many."""
    seen = select(JournalEntry.article_id)
    rows = session.scalars(
        select(Article)
        .where(Article.source == "edgar", Article.severity.is_not(None), Article.id.not_in(seen))
        .order_by(Article.published_at)
    ).all()
    if not rows:
        return 0
    snap, snap_label = {}, None
    st = borrow.status(data_dir)
    if st["last"]:
        files = sorted(f for f in os.listdir(borrow.archive_dir(data_dir)) if f.startswith("usa_"))
        age_h = (datetime.now().timestamp() - os.path.getmtime(os.path.join(borrow.archive_dir(data_dir), files[-1]))) / 3600
        if age_h <= BORROW_MAX_AGE_HOURS:
            snap, snap_label = borrow.latest(data_dir), files[-1][4:17]
    created = 0
    for a in rows:
        sized = [(t.symbol, session.get(Company, t.symbol)) for t in a.tickers]
        sized = [(sym, c) for sym, c in sized if c is not None and c.size_bucket]
        if not sized or not a.signals:
            continue
        sym, company = sized[0]
        primary = ALL_SIGNALS[a.signals[0]]
        b = snap.get(sym) if snap else None
        session.add(
            JournalEntry(
                article_id=a.id,
                ticker=sym,
                cik=a.cik,
                form=a.form,
                signals=a.signals,
                primary_signal=primary.code,
                direction=primary.direction,
                severity=a.severity,
                size_bucket=company.size_bucket,
                public_float=company.public_float,
                filed_at=_aware(a.published_at),
                borrow_fee=b["fee_rate"] if b else None,
                borrow_available=(-1 if b["available"] is None else b["available"]) if b else None,
                borrow_snapshot=snap_label if b else None,
            )
        )
        created += 1
    session.commit()
    return created


def _index_on(series: PriceSeries, d: date) -> int | None:
    import bisect

    i = bisect.bisect_left(series.dates, d)
    return i if i < len(series) and series.dates[i] == d else None


def mark_entry(entry: JournalEntry, series: PriceSeries | None, bench: PriceSeries, today: date) -> None:
    """Fill entry price and horizon returns from price data. Pure function of its inputs."""
    if series is None or len(series) < 2:
        if (today - _aware(entry.filed_at).date()).days > DATA_ENDED_AFTER_DAYS:
            entry.status = "no_data"
        return
    i0 = day0_index(series, _aware(entry.filed_at).astimezone(ET))
    if i0 is None:
        return  # day 0 hasn't printed yet
    i = i0 + ENTRY_DELAY
    if i >= len(series):
        return  # entry close hasn't printed yet
    entry.entry_date = series.dates[i]
    entry.entry_price = series.close[i]
    entry.raw_entry_price = series.raw_close[i] if series.raw_close else series.close[i]
    entry.status = "open"
    b0 = _index_on(bench, series.dates[i])
    for h in HORIZONS:
        j = i + h
        if j >= len(series) or b0 is None:
            continue
        bj = _index_on(bench, series.dates[j])
        if bj is None:
            continue
        abn = (series.close[j] / series.close[i] - 1) - (bench.close[bj] / bench.close[b0] - 1)
        setattr(entry, f"abn_{h}", round(abn, 5))
    if entry.abn_20 is not None:
        entry.status = "complete"
    elif (today - series.dates[-1]).days > DATA_ENDED_AFTER_DAYS:
        entry.status = "data_ended"


def mark(session: Session, data_dir: str, today: date | None = None) -> dict:
    """Update every unfinished entry. Prices come from a per-day cache, so reruns the same day are free."""
    today = today or datetime.now(ET).date()
    pending = session.scalars(select(JournalEntry).where(JournalEntry.status.in_(("waiting", "open")))).all()
    if not pending:
        return {"marked": 0}
    cache = os.path.join(data_dir, "prices_live")
    start = min(_aware(e.filed_at).date() for e in pending) - timedelta(days=10)
    end = today + timedelta(days=1)
    bench = load_prices("IWM", start, end, cache)
    if bench is None:
        return {"marked": 0, "error": "IWM unavailable"}
    by_ticker: dict[str, PriceSeries | None] = {}
    for e in pending:
        if e.ticker not in by_ticker:
            by_ticker[e.ticker] = load_prices(e.ticker, start, end, cache)
        mark_entry(e, by_ticker[e.ticker], bench, today)
        e.marked_at = datetime.now(timezone.utc)
    session.commit()
    counts: dict[str, int] = {}
    for e in pending:
        counts[e.status] = counts.get(e.status, 0) + 1
    return {"marked": len(pending), **counts}


def summary(session: Session, expected: dict[tuple[str, str, int], dict]) -> list[dict]:
    """Live results per (primary signal, size bucket), with the Edge Lab's expectation beside them."""
    groups: dict[tuple[str, str], list[JournalEntry]] = {}
    for e in session.scalars(select(JournalEntry)).all():
        groups.setdefault((e.primary_signal, e.size_bucket or "unknown"), []).append(e)
    out = []
    for (sig, bucket), entries in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        sign = -1 if entries[0].direction == "-" else 1
        row = {"signal": sig, "label": ALL_SIGNALS[sig].label if sig in ALL_SIGNALS else sig,
               "direction": entries[0].direction, "bucket": bucket, "n": len(entries)}
        for h in HORIZONS:
            vals = [getattr(e, f"abn_{h}") for e in entries if getattr(e, f"abn_{h}") is not None]
            row[f"n_{h}"] = len(vals)
            row[f"mean_{h}"] = round(statistics.mean(vals), 4) if vals else None
            row[f"median_{h}"] = round(statistics.median(vals), 4) if vals else None
            row[f"hit_{h}"] = round(sum(1 for v in vals if sign * v > 0) / len(vals), 3) if vals else None
            exp = expected.get((sig, bucket, h))
            row[f"expected_{h}"] = exp["mean_abnormal"] if exp else None
        out.append(row)
    return out
