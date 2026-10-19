"""Hypothetical paper portfolio: what an equal-weight book built from the forward journal would have done.

A pure simulation over journal rows plus price series that the journal marker already cached. It is not
traded, it holds no account and it has no execution path of any kind: positions exist only in this calculation.

Rules (backend/app/paper/AGENTS.md):
- Each JournalEntry opens one position at the journal's own entry (the day 0 + 1 close, `entry_date`),
  fixed notional, LONG for direction '+', SHORT for '-'.
- Held for the signal's evaluation horizon (journal.service.evaluation_horizon: 5 trading days for
  insider_cluster_purchase, 20 otherwise), counted in the stock's own trading days.
- While `max_concurrent` positions are open, new entries are skipped (counted).
- Costs come from the event study's cost model (research.eventstudy.COSTS round trip per size bucket,
  BORROW_APR per bucket for shorts); the journal row's recorded IBKR borrow fee wins when present. The optional
  IWM hedge pays the backtest's hedge round-trip cost (backtest.engine.StrategyConfig.hedge_cost). A short whose
  data ended is closed at the last price plus the backtest's delist penalty (never book a delisting gain).
- Prices are read cache-only (research.prices.load_prices(offline=True)) from `{data_dir}/prices_live`,
  choosing the cache file per entry (newest file containing the entry day, preferring one that reaches the
  horizon), for the stock and the IWM hedge leg alike; a position without a covering cached series is
  'unpriced' and excluded with a count. No network in here.
"""

import bisect
import os
import re
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.engine import TRADING_DAYS, StrategyConfig
from app.journal import service as journal
from app.models import JournalEntry
from app.pipeline.signals import is_forward_test, signal_def
from app.research.eventstudy import BORROW_APR, COSTS, ET
from app.research.prices import PriceSeries, load_prices

LABEL = "Hypothetical: simulated from the forward signal journal, not traded, not investment advice"
COST_MODEL_SOURCE = (
    "Round-trip cost per size bucket and borrow APR for shorts from the event study cost model "
    "(research.eventstudy COSTS / BORROW_APR); recorded IBKR borrow fee when the journal has one; "
    "IWM hedge cost and delisting penalty from the backtest base config (backtest.engine.StrategyConfig)."
)
BENCHMARK = "IWM"
PRICE_CACHE = "prices_live"  # journal.service.mark() writes here
RECENT_POSITIONS = 50
_BASE = StrategyConfig()
HEDGE_COST = _BASE.hedge_cost
DELIST_PENALTY = _BASE.delist_penalty
_CACHE_NAME = re.compile(r"^(?P<ticker>.+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.json$")


def _index_on(series: PriceSeries, d: date) -> int | None:
    i = bisect.bisect_left(series.dates, d)
    return i if i < len(series) and series.dates[i] == d else None


def _newest_first(s: PriceSeries) -> tuple:
    return (s.dates[-1], -s.dates[0].toordinal()) if len(s) else (date.min, 0)


class CachedPrices:
    """Every cached daily series for one ticker under {data_dir}/prices_live, read offline (never fetches).

    journal.service.mark() writes `{ticker}_{start}_{end}.json` with a start that moves forward as older entries
    complete, so the newest file need not cover an old entry. Series are therefore chosen per entry (`covering`):
    the file names are listed once, sorted newest end first, and files are loaded lazily through
    research.prices in offline mode, only when their span contains the day asked for.
    """

    def __init__(self, data_dir: str, ticker: str):
        self.ticker = ticker
        self.cache = os.path.join(data_dir, PRICE_CACHE)
        spans: list[tuple[date, date]] = []
        try:
            names = os.listdir(self.cache)
        except OSError:
            names = []
        for name in names:
            m = _CACHE_NAME.match(name)
            if not m or m["ticker"] != ticker:
                continue
            try:
                spans.append((date.fromisoformat(m["start"]), date.fromisoformat(m["end"])))
            except ValueError:
                continue
        self.spans = sorted(spans, key=lambda se: (se[1], -se[0].toordinal()), reverse=True)
        self._loaded: dict[tuple[date, date], PriceSeries | None] = {}

    def _load(self, span: tuple[date, date]) -> PriceSeries | None:
        if span not in self._loaded:
            try:
                self._loaded[span] = load_prices(self.ticker, span[0], span[1], self.cache, offline=True)
            except (OSError, ValueError):
                self._loaded[span] = None
        return self._loaded[span]

    def __bool__(self) -> bool:
        return bool(self.spans)

    def newest(self) -> PriceSeries | None:
        for span in self.spans:
            s = self._load(span)
            if s is not None and len(s):
                return s
        return None

    def covering(self, d: date) -> list[PriceSeries]:
        """Series containing trading day d, newest end first."""
        out = []
        for span in self.spans:
            if span[0] <= d <= span[1]:
                s = self._load(span)
                if s is not None and _index_on(s, d) is not None:
                    out.append(s)
        return out


class _StaticPrices:
    """Adapter for an injected `price_loader(ticker) -> PriceSeries | list[PriceSeries] | None` (tests)."""

    def __init__(self, series: PriceSeries | list[PriceSeries] | None):
        self.series = [series] if isinstance(series, PriceSeries) else list(series or [])
        self.series.sort(key=_newest_first, reverse=True)

    def __bool__(self) -> bool:
        return bool(self.series)

    def newest(self) -> PriceSeries | None:
        return self.series[0] if self.series else None

    def covering(self, d: date) -> list[PriceSeries]:
        return [s for s in self.series if _index_on(s, d) is not None]


def cached_series(data_dir: str, ticker: str) -> PriceSeries | None:
    """The newest cached daily series for `ticker` (cache-only). build_portfolio chooses per entry instead."""
    return CachedPrices(data_dir, ticker).newest()


def _pick(prices, d: date, horizon: int) -> PriceSeries | None:
    """Per-entry series: the newest cached series containing entry day d that also reaches the horizon, else
    the newest one containing d. One file per position keeps its adjusted closes on a single basis (merging
    files fetched on different days could mix dividend or split adjustments)."""
    cover = prices.covering(d)
    for s in cover:
        if _index_on(s, d) + horizon < len(s):
            return s
    return cover[0] if cover else None


def _close_on_or_before(series: PriceSeries, d: date) -> float | None:
    i = bisect.bisect_right(series.dates, d) - 1
    return series.close[i] if i >= 0 else None


@dataclass
class _Position:
    entry: JournalEntry
    series: PriceSeries
    side: int  # +1 long, -1 short
    horizon: int
    entry_date: date
    entry_price: float
    exit_date: date | None  # None while open
    exit_price: float | None
    cost: float  # round trip, fraction of notional
    borrow_apr: float  # 0 for longs
    hedge_entry: float | None
    hedge_series: PriceSeries | None = None

    def gross(self, px: float) -> float:
        return self.side * (px / self.entry_price - 1)

    def days_held(self, d: date) -> int:
        """Trading days from entry to d (inclusive of d's close), in the stock's own calendar."""
        i0 = _index_on(self.series, self.entry_date) or 0
        return max(0, bisect.bisect_right(self.series.dates, d) - 1 - i0)

    def net_return(self, d: date, px: float, closed: bool) -> float:
        """Net return on notional at date d (price px). Open positions carry half the round-trip cost."""
        r = self.gross(px) - (self.cost if closed else self.cost / 2)
        r -= self.borrow_apr * self.days_held(d) / TRADING_DAYS
        if self.hedge_entry is not None and self.hedge_series is not None:
            b = _close_on_or_before(self.hedge_series, d)
            if b is not None:
                r += -self.side * (b / self.hedge_entry - 1) - (HEDGE_COST if closed else HEDGE_COST / 2)
        return r


def _empty(as_of: date, assumptions: dict, reason: str, **totals) -> dict:
    base = {"pnl": 0.0, "return_pct": 0.0, "n_closed": 0, "n_open": 0, "hit_rate": None,
            "skipped_capacity": 0, "unpriced": 0, "pending": 0, "undirected": 0}
    return {"as_of": as_of.isoformat(), "label": LABEL, "assumptions": assumptions, "equity_curve": [],
            "totals": {**base, **totals}, "by_signal": [], "positions": [], "empty_reason": reason}


def build_portfolio(
    session: Session,
    data_dir: str,
    *,
    notional: float = 10_000,
    max_concurrent: int = 20,
    hedge: bool = False,
    today: date | None = None,
    price_loader=None,
) -> dict:
    """Simulate the hypothetical paper portfolio. Prices default to cache-only reads of the journal's price
    cache, chosen per entry; tests pass `price_loader(ticker) -> PriceSeries | list[PriceSeries] | None`."""
    today = today or datetime.now(ET).date()

    def loader(t: str):
        return CachedPrices(data_dir, t) if price_loader is None else _StaticPrices(price_loader(t))
    capital = notional * max_concurrent
    assumptions = {"notional": notional, "max_concurrent": max_concurrent, "hedge": hedge,
                   "starting_capital": capital, "cost_model": COST_MODEL_SOURCE,
                   "horizons": {"default": journal.DEFAULT_EVALUATION_HORIZON, **journal.EVALUATION_HORIZONS}}

    rows = session.scalars(select(JournalEntry).order_by(JournalEntry.id)).all()
    if not rows:
        return _empty(today, assumptions, "The journal has no entries yet.")

    bench = loader(BENCHMARK)
    if hedge and not bench:
        return _empty(today, assumptions, "The IWM series needed for the hedge leg is not cached yet.",
                      unpriced=len(rows))

    # Candidates: rows the journal has priced (entry_date set), sorted by entry day
    pending = unpriced = undirected = 0
    cands: list[tuple[date, int, JournalEntry, PriceSeries, PriceSeries | None]] = []
    series_cache: dict[str, CachedPrices | _StaticPrices] = {}
    for e in rows:
        if e.direction not in ("+", "-"):  # '?' signals have no expected direction: no position
            undirected += 1
            continue
        if e.status == "waiting" or (e.entry_date is None and e.status != "no_data"):
            pending += 1
            continue
        if e.entry_date is None or e.entry_date > today:
            unpriced += 1
            continue
        if e.ticker not in series_cache:
            series_cache[e.ticker] = loader(e.ticker)
        h = journal.evaluation_horizon(e.primary_signal)
        s = _pick(series_cache[e.ticker], e.entry_date, h)
        b = _pick(bench, e.entry_date, h) if hedge else None
        if s is None or (hedge and b is None):
            unpriced += 1
            continue
        cands.append((e.entry_date, e.id, e, s, b))
    cands.sort(key=lambda c: (c[0], c[1]))

    if not cands:
        reason = ("No journal entry has been priced yet: positions open on the day 0 + 1 close."
                  if pending and not unpriced else "No cached prices for the priced journal entries yet.")
        if not pending and not unpriced:
            reason = "No journal entry has an expected direction (+ or -) yet."
        return _empty(today, assumptions, reason, unpriced=unpriced, pending=pending, undirected=undirected)

    # Open positions chronologically, respecting capacity
    positions: list[_Position] = []
    skipped = 0
    for d, _id, e, s, b in cands:
        open_now = sum(1 for p in positions if p.exit_date is None or p.exit_date > d)
        if open_now >= max_concurrent:
            skipped += 1
            continue
        side = -1 if e.direction == "-" else 1
        h = journal.evaluation_horizon(e.primary_signal)
        bucket = e.size_bucket if e.size_bucket in COSTS else "small"
        i = _index_on(s, d)
        j = i + h
        exit_date = exit_price = None
        if j < len(s) and s.dates[j] <= today:
            exit_date, exit_price = s.dates[j], s.close[j]
        elif (today - s.dates[-1]).days > journal.DATA_ENDED_AFTER_DAYS:  # data ended before the horizon
            exit_date, exit_price = s.dates[-1], s.close[-1] * (1 + DELIST_PENALTY if side < 0 else 1)
        apr = 0.0
        if side < 0:
            apr = e.borrow_fee if e.borrow_fee is not None else BORROW_APR[bucket]
        positions.append(_Position(
            entry=e, series=s, side=side, horizon=h, entry_date=d, entry_price=s.close[i],
            exit_date=exit_date, exit_price=exit_price, cost=COSTS[bucket], borrow_apr=apr,
            hedge_entry=b.close[_index_on(b, d)] if b is not None else None, hedge_series=b,
        ))

    def value(p: _Position, d: date) -> tuple[float, bool] | None:
        """(net return, closed) at date d, or None before entry."""
        if d < p.entry_date:
            return None
        if p.exit_date is not None and d >= p.exit_date:
            return p.net_return(p.exit_date, p.exit_price, True), True
        px = _close_on_or_before(p.series, d)
        return p.net_return(d, px, False), False

    # Equity curve over the union of every calendar in use (each position's stock and hedge series plus the
    # newest IWM file), so a position priced from an older cache file still starts the curve on its entry day
    start = positions[0].entry_date
    calendars = [p.series for p in positions] + [p.hedge_series for p in positions if p.hedge_series is not None]
    newest_bench = bench.newest() if bench else None
    if newest_bench is not None:
        calendars.append(newest_bench)
    days = sorted({d for c in calendars for d in c.dates if start <= d <= today})
    curve = []
    for d in days:
        pnl, n_open = 0.0, 0
        for p in positions:
            v = value(p, d)
            if v is None:
                continue
            pnl += notional * v[0]
            n_open += 0 if v[1] else 1
        curve.append({"date": d.isoformat(), "equity": round(capital + pnl, 2), "open_positions": n_open})

    # Final state per position
    final = []
    for p in positions:
        last_day = min(today, p.series.dates[-1]) if p.exit_date is None else p.exit_date
        r, closed = value(p, max(last_day, p.entry_date))
        final.append((p, r, closed))

    def stats(items):
        closed = [r for _, r, c in items if c]
        return {
            "n": len(items),
            "n_closed": len(closed),
            "pnl": round(sum(notional * r for _, r, _ in items), 2),
            "mean_return_net": round(sum(closed) / len(closed), 5) if closed else None,
            "hit_rate": round(sum(1 for r in closed if r > 0) / len(closed), 3) if closed else None,
        }

    tot = stats(final)
    by_sig: dict[str, list] = {}
    for item in final:
        by_sig.setdefault(item[0].entry.primary_signal, []).append(item)
    by_signal = []
    for sig, items in sorted(by_sig.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        sdef = signal_def(sig)
        by_signal.append({
            "signal": sig, "label": sdef.label if sdef else sig, "direction": items[0][0].entry.direction,
            "horizon": journal.evaluation_horizon(sig), "forward_test": is_forward_test(sig),
            "forward_test_label": journal.forward_test_label(sig), **stats(items),
        })

    recent = sorted(final, key=lambda it: (it[0].entry_date, it[0].entry.id), reverse=True)[:RECENT_POSITIONS]
    return {
        "as_of": today.isoformat(),
        "label": LABEL,
        "assumptions": assumptions,
        "equity_curve": curve,
        "totals": {
            "pnl": tot["pnl"],
            "return_pct": round(tot["pnl"] / capital, 5) if capital else 0.0,
            "n_closed": tot["n_closed"],
            "n_open": tot["n"] - tot["n_closed"],
            "hit_rate": tot["hit_rate"],
            "skipped_capacity": skipped,
            "unpriced": unpriced,
            "pending": pending,
            "undirected": undirected,
        },
        "by_signal": by_signal,
        "positions": [
            {"ticker": p.entry.ticker, "signal": p.entry.primary_signal, "side": "long" if p.side > 0 else "short",
             "size_bucket": p.entry.size_bucket, "horizon": p.horizon, "entry_date": p.entry_date.isoformat(),
             "exit_date": p.exit_date.isoformat() if p.exit_date else None,
             "status": "closed" if closed else "open", "net_return": round(r, 5), "pnl": round(notional * r, 2)}
            for p, r, closed in recent
        ],
        "empty_reason": None,
    }
