"""Daily portfolio simulation of a filing-event short strategy.

One trading day at a time, in this order:
  1. Mark open positions to today's close and charge one day of borrow fee.
  2. Exit positions that hit the stop, the holding period, or the end of
     their price data (delisting/halt), paying half the round-trip cost.
  3. Enter today's new events, subject to every filter, paying half the cost.
  4. Record equity, exposure and position count.

Entries happen at the close of the entry day, which is day 0 (first close a
trader could act on after EDGAR acceptance, see research.eventstudy.day0_index)
plus `entry_delay` days. Every skipped event is logged with its reason, so
the gap between "signals" and "trades" is visible.

Returns use adjusted closes (safe across reverse splits). Filters that
depend on the traded price (the $1 floor) use the unadjusted price.
"""

import bisect
import random
from dataclasses import asdict, dataclass, field, replace
from datetime import date

from app.backtest.universe import OfferingEvent
from app.research.eventstudy import day0_index
from app.research.prices import PriceSeries

TRADING_DAYS = 252


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "base"
    hold_days: int = 20
    # Day 0 is often a >10% drop, which triggers Rule 201 (shorts only above the bid), so the
    # base case waits one more close instead of assuming a fill into the selling.
    entry_delay: int = 1
    stop_loss: float | None = 0.40  # cover if the close is 40% above entry (squeeze guard)
    stop_slippage: float = 0.05  # stops in nano caps fill well past the trigger
    capital: float = 100_000.0
    max_positions: int = 25
    position_pct: float = 0.03  # target notional per position, as a share of current equity
    max_gross_short: float = 1.0  # total short notional / equity
    max_adv_pct: float = 0.05  # notional cap as a share of 20-day median dollar volume
    min_price: float = 1.0  # unadjusted price floor (margin is $2.50/share below $5)
    min_adv: float = 200_000.0  # minimum 20-day median dollar volume, measured before entry
    cost_round_trip: float = 0.03  # spread + slippage for nano caps, both sides
    cost_mult: float = 1.0
    borrow_apr: float = 0.75
    availability: float = 0.70  # probability shares can be borrowed for any given trade
    recall_prob: float = 0.02  # daily chance the lender recalls the shares
    recall_penalty: float = 0.02  # forced cover price premium on a recall
    delist_penalty: float = 0.10  # cover at last price + 10% when data ends (never book the delisting gain)
    seed: int = 1
    hedge: bool = True  # long IWM against each short, same notional
    hedge_cost: float = 0.0004  # round trip for IWM

    def key(self) -> str:
        d = asdict(self)
        d.pop("name")
        return "|".join(f"{k}={v}" for k, v in sorted(d.items()))

    def with_(self, **kw) -> "StrategyConfig":
        return replace(self, **kw)


@dataclass
class Position:
    event: OfferingEvent
    series: PriceSeries
    entry_date: date
    entry_index: int  # index into series
    entry_price: float
    raw_entry_price: float
    shares: float  # positive count of shares short
    notional: float
    hedge_shares: float
    hedge_entry: float
    last_price: float
    borrow_paid: float = 0.0
    costs_paid: float = 0.0
    days_held: int = 0


@dataclass
class SimResult:
    config: StrategyConfig
    dates: list[date]
    equity: list[float]
    gross_exposure: list[float]  # (shorts + hedge) / equity
    positions: list[int]
    trades: list[dict]
    skipped: list[dict]
    signals: int
    extra: dict = field(default_factory=dict)


def _index_on(series: PriceSeries, d: date) -> int | None:
    i = bisect.bisect_left(series.dates, d)
    return i if i < len(series) and series.dates[i] == d else None


def _price_on_or_before(series: PriceSeries, d: date) -> tuple[float, int] | None:
    i = bisect.bisect_right(series.dates, d) - 1
    return (series.close[i], i) if i >= 0 else None


def entry_point(event: OfferingEvent, series: PriceSeries, entry_delay: int) -> int | None:
    i0 = day0_index(series, event.accepted_et)
    if i0 is None:
        return None
    i = i0 + entry_delay
    return i if i < len(series) else None


def simulate(
    events: list[OfferingEvent],
    prices: dict[str, PriceSeries | None],
    bench: PriceSeries,
    cfg: StrategyConfig,
    start: date,
    end: date,
) -> SimResult:
    rng = random.Random(cfg.seed)
    half_cost = cfg.cost_round_trip * cfg.cost_mult / 2
    half_hedge = cfg.hedge_cost * cfg.cost_mult / 2

    # Group candidate entries by entry date
    entries: dict[date, list[tuple[OfferingEvent, PriceSeries, int]]] = {}
    skipped: list[dict] = []

    def skip(ev: OfferingEvent, reason: str, **kw) -> None:
        skipped.append({"ticker": ev.ticker, "accepted": ev.accepted_et.isoformat(), "reason": reason, **kw})

    signals = 0
    for ev in events:
        if not (start <= ev.accepted_et.date() <= end):
            continue
        signals += 1
        series = prices.get(ev.ticker)
        if series is None or len(series) < 30:
            skip(ev, "no_price_data")
            continue
        i = entry_point(ev, series, cfg.entry_delay)
        if i is None:
            skip(ev, "no_trading_after_filing")
            continue
        entries.setdefault(series.dates[i], []).append((ev, series, i))

    calendar = [d for d in bench.dates if start <= d]
    cash = cfg.capital
    open_pos: dict[str, Position] = {}
    trades: list[dict] = []
    out_dates, out_equity, out_gross, out_n = [], [], [], []
    last_entry_date = max(entries) if entries else start

    def bench_px(d: date) -> float:
        got = _price_on_or_before(bench, d)
        return got[0] if got else bench.close[0]

    def close_position(p: Position, d: date, price: float, reason: str) -> None:
        nonlocal cash
        cost = p.shares * price * half_cost
        cash -= p.shares * price + cost
        p.costs_paid += cost
        hedge_pnl = 0.0
        if p.hedge_shares:
            hpx = bench_px(d)
            hcost = p.hedge_shares * hpx * half_hedge
            cash += p.hedge_shares * hpx - hcost
            p.costs_paid += hcost
            hedge_pnl = p.hedge_shares * (hpx - p.hedge_entry)
        short_pnl = p.shares * (p.entry_price - price)
        net = short_pnl + hedge_pnl - p.costs_paid - p.borrow_paid
        trades.append(
            {
                "ticker": p.event.ticker,
                "company": p.event.company,
                "form": p.event.form,
                "filed": p.event.accepted_et.isoformat(),
                "filing_url": p.event.filing_url,
                "public_float": p.event.public_float,
                "entry_date": p.entry_date.isoformat(),
                "exit_date": d.isoformat(),
                "days_held": p.days_held,
                "entry_price": round(p.raw_entry_price, 4),
                "exit_move": round(price / p.entry_price - 1, 4),
                "notional": round(p.notional, 2),
                "short_pnl": round(short_pnl, 2),
                "hedge_pnl": round(hedge_pnl, 2),
                "costs": round(p.costs_paid, 2),
                "borrow": round(p.borrow_paid, 2),
                "net_pnl": round(net, 2),
                "net_return": round(net / p.notional, 4),
                "exit_reason": reason,
            }
        )

    for d in calendar:
        if d > end and not open_pos and d > last_entry_date:
            break
        # 1-2: mark, charge borrow, exits
        for tkr in list(open_pos):
            p = open_pos[tkr]
            idx = _index_on(p.series, d)
            if idx is None:
                if d > p.series.dates[-1]:
                    close_position(p, d, p.last_price * (1 + cfg.delist_penalty), "data_ended")
                    del open_pos[tkr]
                continue  # halted / no print today: carry last price
            borrow = p.shares * p.last_price * cfg.borrow_apr / TRADING_DAYS
            cash -= borrow
            p.borrow_paid += borrow
            p.last_price = p.series.close[idx]
            p.days_held = idx - p.entry_index
            if cfg.stop_loss is not None and p.last_price >= p.entry_price * (1 + cfg.stop_loss):
                close_position(p, d, p.last_price * (1 + cfg.stop_slippage), "stop_loss")
                del open_pos[tkr]
            elif cfg.recall_prob and rng.random() < cfg.recall_prob:
                close_position(p, d, p.last_price * (1 + cfg.recall_penalty), "recall")
                del open_pos[tkr]
            elif p.days_held >= cfg.hold_days:
                close_position(p, d, p.last_price, "time")
                del open_pos[tkr]

        equity_now = cash + sum(-p.shares * p.last_price + p.hedge_shares * bench_px(d) for p in open_pos.values())

        # 3: entries (candidates were already limited to events filed inside the period)
        for ev, series, i in entries.get(d, []):
            if ev.ticker in open_pos:
                skip(ev, "already_short")
                continue
            if len(open_pos) >= cfg.max_positions:
                skip(ev, "max_positions")
                continue
            raw_px = series.raw_close[i] if series.raw_close else series.close[i]
            if raw_px < cfg.min_price:
                skip(ev, "below_price_floor", price=round(raw_px, 4))
                continue
            window = sorted(series.dollar_volume[max(0, i - 20) : i]) if series.dollar_volume else []
            adv = window[len(window) // 2] if window else 0.0  # median: offering-day spikes would overstate it
            if adv < cfg.min_adv:
                skip(ev, "illiquid", adv=round(adv))
                continue
            if rng.random() >= cfg.availability:
                skip(ev, "no_borrow")
                continue
            notional = min(cfg.position_pct * equity_now, cfg.max_adv_pct * adv)
            if notional < 250:
                skip(ev, "position_too_small", adv=round(adv))
                continue
            short_book = sum(p.shares * p.last_price for p in open_pos.values())
            if short_book + notional > cfg.max_gross_short * equity_now:
                skip(ev, "gross_limit")
                continue
            price = series.close[i]
            shares = notional / price
            cost = notional * half_cost
            cash += notional - cost
            hedge_shares, hpx = 0.0, bench_px(d)
            if cfg.hedge:
                hedge_shares = notional / hpx
                hcost = notional * half_hedge
                cash -= notional + hcost
                cost += hcost
            open_pos[ev.ticker] = Position(
                event=ev, series=series, entry_date=d, entry_index=i, entry_price=price,
                raw_entry_price=raw_px, shares=shares, notional=notional, hedge_shares=hedge_shares,
                hedge_entry=hpx, last_price=price, costs_paid=cost,
            )

        # 4: record
        bpx = bench_px(d)
        shorts = sum(p.shares * p.last_price for p in open_pos.values())
        hedges = sum(p.hedge_shares * bpx for p in open_pos.values())
        equity = cash - shorts + hedges
        out_dates.append(d)
        out_equity.append(equity)
        out_gross.append((shorts + hedges) / equity if equity > 0 else 0.0)
        out_n.append(len(open_pos))
        if equity <= 0:
            break  # ruin

    return SimResult(cfg, out_dates, out_equity, out_gross, out_n, trades, skipped, signals)
