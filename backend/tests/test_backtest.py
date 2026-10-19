import random
from datetime import date, datetime, timedelta

import pytest

from app.backtest import borrow
from app.backtest.engine import StrategyConfig, simulate
from app.backtest.stats import drawdowns, dsr, min_trl, psr, sharpe
from app.backtest.universe import OfferingEvent
from app.research.eventstudy import ET
from app.research.prices import PriceSeries, parse_chart

START = date(2024, 1, 1)
DAYS = [START + timedelta(days=i) for i in range(120) if (START + timedelta(days=i)).weekday() < 5]

# Deterministic config: every name borrowable, no recalls, no costs unless a test adds them
CLEAN = StrategyConfig(
    entry_delay=0, availability=1.0, recall_prob=0.0, cost_round_trip=0.0, borrow_apr=0.0,
    hedge=False, min_adv=0.0, max_adv_pct=1.0, position_pct=0.10,
)


def series(closes, raw=None, dvol=1e6, n=None):
    n = n or len(closes)
    return PriceSeries("X", DAYS[:n], list(closes[:n]), list((raw or closes)[:n]), [dvol] * n)


BENCH = PriceSeries("IWM", DAYS, [100.0] * len(DAYS), [100.0] * len(DAYS), [1e9] * len(DAYS))


def event(day_index=5, ticker="X"):
    d = DAYS[day_index]
    return OfferingEvent(1, ticker, "X Corp", "424B5", datetime(d.year, d.month, d.day, 9, 0, tzinfo=ET), "0000000000-24-000001", 2e7)


def run(cfg, closes, **kw):
    prices = {"X": series(closes, **kw)}
    return simulate([event()], prices, BENCH, cfg, DAYS[0], DAYS[60])


def test_short_profits_from_decline_and_exits_on_time():
    closes = [10.0] * 6 + [10.0 * 0.99**i for i in range(1, 80)]
    res = run(CLEAN.with_(hold_days=10), closes)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t["exit_reason"] == "time" and t["days_held"] == 10
    assert t["net_pnl"] > 0 and t["exit_move"] == pytest.approx(0.99**10 - 1, abs=1e-3)
    assert res.equity[-1] == pytest.approx(100_000 + t["net_pnl"], rel=1e-6)


def test_costs_and_borrow_reduce_pnl():
    closes = [10.0] * 90
    res = run(CLEAN.with_(hold_days=10, cost_round_trip=0.03, borrow_apr=0.75), closes)
    t = res.trades[0]
    assert t["short_pnl"] == 0
    assert t["costs"] == pytest.approx(t["notional"] * 0.03, rel=1e-3)
    assert t["borrow"] == pytest.approx(t["notional"] * 0.75 * 10 / 252, rel=1e-3)
    assert t["net_pnl"] == pytest.approx(-(t["costs"] + t["borrow"]), rel=1e-6)


def test_stop_loss_with_slippage():
    closes = [10.0] * 6 + [10.0, 12.0, 15.0] + [15.0] * 80
    res = run(CLEAN.with_(stop_loss=0.40, stop_slippage=0.05), closes)
    t = res.trades[0]
    assert t["exit_reason"] == "stop_loss"
    assert t["exit_move"] == pytest.approx(1.5 * 1.05 - 1, abs=1e-3)


def test_price_floor_uses_unadjusted_price():
    closes = [10.0] * 90  # adjusted for a later reverse split
    raw = [0.5] * 90  # what actually printed
    res = run(CLEAN, closes, raw=raw)
    assert res.trades == [] and res.skipped[0]["reason"] == "below_price_floor"


def test_delisting_covers_at_penalty_not_zero():
    closes = [10.0] * 30  # price history stops on day 30 while the short is still open
    res = run(CLEAN.with_(delist_penalty=0.10, hold_days=60), closes, n=30)
    t = res.trades[0]
    assert t["exit_reason"] == "data_ended"
    assert t["exit_move"] == pytest.approx(0.10, abs=1e-6)


def test_liquidity_and_gross_limits():
    res = run(CLEAN.with_(min_adv=5e6), [10.0] * 90)
    assert res.skipped[0]["reason"] == "illiquid"
    prices = {t: series([10.0] * 90) for t in "ABC"}
    evs = [event(5, t) for t in "ABC"]
    res = simulate(evs, prices, BENCH, CLEAN.with_(position_pct=0.4, max_gross_short=1.0), DAYS[0], DAYS[60])
    assert len(res.trades) == 2 and [s["reason"] for s in res.skipped] == ["gross_limit"]


def test_hedge_offsets_market_move():
    bench = PriceSeries("IWM", DAYS, [100.0 * 0.99**i for i in range(len(DAYS))], [1.0] * len(DAYS), [1e9] * len(DAYS))
    closes = [10.0 * 0.99**i for i in range(len(DAYS))]  # stock falls exactly with the market
    res = simulate([event()], {"X": series(closes)}, bench, CLEAN.with_(hedge=True, hold_days=10), DAYS[0], DAYS[60])
    t = res.trades[0]
    assert t["short_pnl"] > 0 and t["hedge_pnl"] < 0
    assert abs(t["net_pnl"]) < 0.02 * t["notional"]


def test_stats():
    rng = random.Random(3)
    good = [0.0015 + rng.gauss(0, 0.01) for _ in range(750)]
    flat = [rng.gauss(0, 0.01) for _ in range(750)]
    assert sharpe(good) > sharpe(flat)
    assert psr(good) > 0.95 > psr(flat)
    # Deflating against many trials can only lower the probability
    trials = [rng.gauss(0, 1) for _ in range(50)]
    assert dsr(good, trials)[0] <= psr(good)
    assert min_trl(good) is not None and min_trl([-abs(x) for x in good]) is None
    _, max_dd, _ = drawdowns([100, 120, 90, 130])
    assert max_dd == pytest.approx(0.25)


def test_parse_chart_unadjusts_reverse_split():
    payload = {"chart": {"result": [{
        "timestamp": [1700000000, 1700086400, 1700172800],
        "events": {"splits": {"1700086400": {"numerator": 1, "denominator": 10}}},
        "indicators": {"adjclose": [{"adjclose": [5.0, 5.0, 5.0]}], "quote": [{"close": [5.0, 5.0, 5.0], "volume": [100, 100, 100]}]},
    }]}}
    s = parse_chart("X", payload)
    assert s.raw_close == [0.5, 5.0, 5.0]  # before the 1-for-10 split it traded at $0.50
    assert s.dollar_volume == [500.0, 500.0, 500.0]


def test_borrow_file_parse():
    raw = b"#BOF|2026.10.16|13:04:30\n#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|\nAAA|USD|A|1|X|3.3|0.25|>10000000|F|\nBBB|USD|B|2|X|-80|85.5|1500|F|\nCCC|USD|C|3|X|0|NA|0|F|\n#EOF|3\n"
    p = borrow.parse(raw)
    assert p["AAA"] == {"fee_rate": 0.0025, "available": None}
    assert p["BBB"] == {"fee_rate": 0.855, "available": 1500}
    assert p["CCC"]["available"] == 0 and p["CCC"]["fee_rate"] is None


def test_overfitting_block_publishes_exact_dsr_inputs():
    import statistics

    from app.backtest.report import overfitting_block

    rng = random.Random(3)
    rets = {"A": [rng.gauss(0.0005, 0.01) for _ in range(300)], "B": [rng.gauss(0.0, 0.01) for _ in range(120)]}
    trials = {"A|x": 0.4, "A|y": 1.1, "B|x": -0.2, "B|y": 0.7}
    out = overfitting_block(rets, trials)
    for key in ("A", "B"):  # existing keys unchanged
        val, bench = dsr(rets[key], list(trials.values()))
        assert out[f"dsr_{key}"] == round(val, 3) and out[f"luck_sharpe_{key}"] == round(bench, 2)
    assert out["trials"] == 4
    assert out["n_returns_A"] == 300 and out["n_returns_B"] == 120
    assert out["trial_sharpe_std"] == round(statistics.stdev(trials.values()), 4)
    assert overfitting_block({"A": rets["A"]}, {"A|x": 0.4})["trial_sharpe_std"] == 0.0  # < 2 trials: no luck benchmark
