"""Build the full backtest report: base runs, stress tests, walk-forward,
capacity, overfitting statistics, live-readiness gates and a verdict.

Every simulation is appended to the run log (data/backtests/runs.jsonl), and
the number of distinct configurations ever tried feeds the Deflated Sharpe
Ratio. Trying more variants makes the bar higher, which is the point.

The base configuration was fixed from the event study before any backtest
ran (20-day hold, entry at day-0 close). Period A (2020-23) never touched the
signal's discovery, so its base result is the headline.
"""

import json
import logging
import os
import re
import statistics
import subprocess
import uuid
from datetime import date, datetime, timezone

from app.backtest import borrow
from app.backtest.engine import SimResult, StrategyConfig, simulate
from app.backtest.stats import (
    block_bootstrap,
    min_trl,
    daily_returns,
    drawdowns,
    dsr,
    period_returns,
    summarize,
)
from app.backtest.universe import PERIODS, PRICE_END, PRICE_START, OfferingEvent, Period, build_universe
from app.config import get_settings
from app.research.prices import PriceSeries, load_prices

log = logging.getLogger("backtest")

STRATEGY = {
    "id": "nano_offering_short",
    "name": "Short nano caps after a priced offering",
    "summary": (
        "When a company with under $50M public float files a final prospectus (424B4/424B5), short it at the close "
        "one trading day after the first close a trader could act on, hedge with an equal long position in IWM, and "
        "cover after 20 trading days, or early if the close rises 40% above entry."
    ),
    "hypothesis": (
        "Priced offerings in the smallest companies are followed by continued selling: new shares and warrants hit "
        "the market, and these issuers often raise again. The Edge Lab measured -13.7% vs ordinary days over 20 "
        "trading days (t=-5.7) in Oct 2023 - Aug 2026."
    ),
}

BASE = StrategyConfig()

STRESS = [
    ("Enter at day-0 close (optimistic)", dict(entry_delay=0)),
    ("Enter two days later", dict(entry_delay=2)),
    ("Costs x2", dict(cost_mult=2.0)),
    ("Costs x3", dict(cost_mult=3.0)),
    ("Borrow 150%/yr", dict(borrow_apr=1.5)),
    ("Borrow 300%/yr", dict(borrow_apr=3.0)),
    ("Half of names unborrowable", dict(availability=0.5)),
    ("70% of names unborrowable", dict(availability=0.3)),
    ("Stop at +25%", dict(stop_loss=0.25)),
    ("No stop-loss", dict(stop_loss=None)),
    ("No IWM hedge", dict(hedge=False)),
    ("$2 price floor", dict(min_price=2.0)),
    ("$0.50 price floor", dict(min_price=0.5)),
    ("Worst case: costs x2, borrow 300%, half unborrowable, 2-day delay",
     dict(cost_mult=2.0, borrow_apr=3.0, availability=0.5, entry_delay=2)),
]
AVAILABILITY_SEEDS = [1, 2, 3, 4, 5]
MC_SEEDS = list(range(1, 21))  # borrow availability and recalls are random: show the spread

GRID = [dict(hold_days=h, stop_loss=s) for h in (5, 10, 15, 20) for s in (0.25, 0.40, None)]
CAPITALS = [10_000, 100_000, 1_000_000, 5_000_000]


# --- Run log ---------------------------------------------------------------------


def runs_path(data_dir: str) -> str:
    return os.path.join(data_dir, "backtests", "runs.jsonl")


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def trial_key(cfg: StrategyConfig) -> str:
    """Identity of a strategy variant for overfitting purposes: the seed is luck, not a new idea."""
    return cfg.with_(seed=0).key()


def log_run(data_dir: str, period: Period, label: str, res: SimResult, metrics: dict, kind: str) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now(timezone.utc).isoformat(),
        "strategy": STRATEGY["id"],
        "period": period.key,
        "label": label,
        "kind": kind,  # "search" counts toward the Deflated Sharpe trials; "robustness" does not
        "config_key": res.config.key(),
        "trial_key": trial_key(res.config),
        "config": {k: v for k, v in res.config.__dict__.items()},
        "signals": res.signals,
        "metrics": {k: metrics.get(k) for k in ("total_return", "cagr", "sharpe", "max_drawdown", "trades", "win_rate")},
        "git": git_sha(),
    }
    path = runs_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def is_search(run: dict) -> bool:
    """Runs logged before `kind` existed: the base case and walk-forward grid were search attempts."""
    if "kind" in run:
        return run["kind"] == "search"
    return run["label"] == "base" or run["label"].startswith("walk-forward")


def trial_id(run: dict) -> str:
    """Period + strategy variant, ignoring the random seed (legacy entries lack trial_key)."""
    key = run.get("trial_key") or re.sub(r"seed=\d+", "seed=0", run["config_key"])
    return f"{run['period']}|{key}"


def read_runs(data_dir: str) -> list[dict]:
    path = runs_path(data_dir)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --- Helpers ---------------------------------------------------------------------


def weekly(dates: list[date], values: list[float]) -> list[list]:
    """Downsample a daily series to the last value of each ISO week (for charts)."""
    out: dict[tuple, list] = {}
    for d, v in zip(dates, values):
        out[d.isocalendar()[:2]] = [d.isoformat(), round(v, 4)]
    return list(out.values())


def skip_summary(res: SimResult) -> dict:
    counts: dict[str, int] = {}
    for s in res.skipped:
        counts[s["reason"]] = counts.get(s["reason"], 0) + 1
    return counts


class Runner:
    def __init__(self, data_dir: str, events: dict[str, list[OfferingEvent]], prices, bench: PriceSeries):
        self.data_dir = data_dir
        self.events = events
        self.prices = prices
        self.bench = bench
        self.trial_sharpes: dict[str, float] = {}  # config_key -> Sharpe, both periods pooled by key+period

    def run(self, period: Period, cfg: StrategyConfig, label: str, kind: str = "robustness") -> tuple[SimResult, dict]:
        res = simulate(self.events[period.key], self.prices, self.bench, cfg, period.start, period.end)
        metrics = summarize(res.dates, res.equity, res.gross_exposure, res.trades)
        metrics["signals"] = res.signals
        metrics["fill_rate"] = round(metrics["trades"] / res.signals, 3) if res.signals else 0.0
        metrics["skipped"] = skip_summary(res)
        if kind == "search":
            self.trial_sharpes[f"{period.key}|{trial_key(cfg)}"] = metrics["sharpe"]
        log_run(self.data_dir, period, label, res, metrics, kind)
        return res, metrics

    def run_avg_availability(self, period: Period, cfg: StrategyConfig, label: str) -> dict:
        """Random borrow availability: average key metrics over several seeds."""
        runs = [self.run(period, cfg.with_(seed=s), f"{label} (seed {s})")[1] for s in AVAILABILITY_SEEDS]
        keys = ("total_return", "cagr", "sharpe", "max_drawdown", "trades", "win_rate")
        return {k: round(statistics.mean(r[k] for r in runs), 4) for k in keys} | {"seeds": len(runs)}


# --- Report ----------------------------------------------------------------------


def run_period(runner: Runner, period: Period) -> dict:
    res, metrics = runner.run(period, BASE, "base", kind="search")
    rets = daily_returns(res.equity)
    dd_series, _, _ = drawdowns(res.equity)
    stress = []
    for label, kw in STRESS:
        cfg = BASE.with_(name=label, **kw)
        m = runner.run_avg_availability(period, cfg, label)
        stress.append({"label": label, "changes": kw, **{k: m[k] for k in ("total_return", "cagr", "sharpe", "max_drawdown", "trades")}})
    capacity = []
    for cap in CAPITALS:
        m = runner.run(period, BASE.with_(name=f"capital {cap}", capital=float(cap)), f"capital ${cap:,}")[1]
        capacity.append({"capital": cap, **{k: m[k] for k in ("total_return", "cagr", "sharpe", "max_drawdown", "trades", "fill_rate")}})
    mc = [runner.run(period, BASE.with_(seed=sd), f"base seed {sd}")[1] for sd in MC_SEEDS]
    pct_of = lambda xs, q: sorted(xs)[min(len(xs) - 1, int(q * len(xs)))]  # noqa: E731
    monte_carlo = {
        "runs": len(mc),
        **{f"{k}_{name}": round(pct_of([r[k] for r in mc], q), 4)
           for k in ("total_return", "sharpe", "max_drawdown") for name, q in (("p05", 0.05), ("p50", 0.5), ("p95", 0.95))},
    }
    by_form = {}
    for form in sorted({t["form"] for t in res.trades}):
        ts = [t for t in res.trades if t["form"] == form]
        by_form[form] = {"trades": len(ts), "avg_return": round(statistics.mean(t["net_return"] for t in ts), 4),
                         "win_rate": round(sum(1 for t in ts if t["net_pnl"] > 0) / len(ts), 3),
                         "net_pnl": round(sum(t["net_pnl"] for t in ts), 2)}
    return {
        "period": period.__dict__ | {"start": period.start.isoformat(), "end": period.end.isoformat()},
        "metrics": metrics,
        "bootstrap": block_bootstrap(rets),
        "equity_curve": weekly(res.dates, res.equity),
        "drawdown_curve": weekly(res.dates, dd_series),
        "exposure_curve": weekly(res.dates, res.gross_exposure),
        "monthly_returns": period_returns(res.dates, res.equity, lambda d: d.strftime("%Y-%m")),
        "yearly_returns": period_returns(res.dates, res.equity, lambda d: str(d.year)),
        "trades": res.trades,
        "skipped_sample": res.skipped[:300],
        "stress": stress,
        "capacity": capacity,
        "monte_carlo": monte_carlo,
        "by_form": by_form,
        "min_track_record_days": min_trl(rets),
        "_rets": rets,
    }


FRICTIONLESS = BASE.with_(
    name="frictionless", entry_delay=0, stop_loss=None, cost_round_trip=0.0, borrow_apr=0.0, availability=1.0,
    recall_prob=0.0, delist_penalty=0.0, min_price=0.0, min_adv=0.0, max_adv_pct=1.0, position_pct=0.01,
    max_positions=500, max_gross_short=10.0, hedge_cost=0.0,
)
WATERFALL = [
    ("Gross drift: every signal, day-0 close, no frictions", {}),
    ("Wait one more day (Rule 201)", dict(entry_delay=BASE.entry_delay)),
    ("Tradable names only ($1 floor, $200k volume, size limits)",
     dict(min_price=BASE.min_price, min_adv=BASE.min_adv, max_adv_pct=BASE.max_adv_pct, position_pct=BASE.position_pct,
          max_positions=BASE.max_positions, max_gross_short=BASE.max_gross_short)),
    ("Spread and slippage (3% round trip)", dict(cost_round_trip=BASE.cost_round_trip, hedge_cost=BASE.hedge_cost)),
    ("Borrow fee (75%/yr)", dict(borrow_apr=BASE.borrow_apr)),
    ("Squeeze stop (+40%, filled 5% worse)", dict(stop_loss=BASE.stop_loss)),
    ("Lender recalls (2%/day)", dict(recall_prob=BASE.recall_prob)),
    ("30% of names unborrowable", dict(availability=BASE.availability)),
    ("No credit for delistings (= base case)", dict(delist_penalty=BASE.delist_penalty)),
]


def waterfall(runner: Runner, period: Period) -> list[dict]:
    """Add one real-world friction at a time, from frictionless to the base case."""
    cfg, out = FRICTIONLESS, []
    for label, changes in WATERFALL:
        cfg = cfg.with_(**changes)
        res, m = runner.run(period, cfg, f"waterfall: {label}")
        rets = [t["net_return"] for t in res.trades]
        out.append({
            "step": label,
            "trades": m["trades"],
            "avg_trade_return": round(statistics.mean(rets), 4) if rets else 0.0,
            "median_trade_return": round(statistics.median(rets), 4) if rets else 0.0,
            "total_return": m["total_return"],
            "sharpe": m["sharpe"],
        })
    assert cfg.key() == BASE.key(), "waterfall must end exactly at the base config"
    return out


BORROW_GRID = [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0, 1.5]


def borrow_sensitivity(runner: Runner, period: Period) -> dict:
    """Base case at different flat borrow fees, and the fee at which it breaks even.

    Robustness only: the base config and gates are unchanged. A borrow-filtered variant
    would be a new strategy and must be pre-registered and tested on fresh data.
    """
    rows = []
    for apr in BORROW_GRID:
        m = runner.run_avg_availability(period, BASE.with_(name=f"borrow {apr}", borrow_apr=apr), f"borrow sensitivity {apr:.0%}")
        rows.append({"borrow_apr": apr, "total_return": m["total_return"], "cagr": m["cagr"], "sharpe": m["sharpe"]})
    breakeven = None
    for lo, hi in zip(rows, rows[1:]):
        if lo["total_return"] > 0 >= hi["total_return"]:
            frac = lo["total_return"] / (lo["total_return"] - hi["total_return"])
            breakeven = round(lo["borrow_apr"] + frac * (hi["borrow_apr"] - lo["borrow_apr"]), 3)
    if breakeven is None and rows and rows[0]["total_return"] <= 0:
        breakeven = 0.0  # loses money even with free borrow
    return {"rows": rows, "breakeven_apr": breakeven}


def walk_forward(runner: Runner) -> dict:
    """Pick hold/stop on period A only, then apply the winner unchanged to period B."""
    a, b = PERIODS["A"], PERIODS["B"]
    grid = []
    for kw in GRID:
        cfg = BASE.with_(name=f"grid {kw}", **kw)
        m = runner.run(a, cfg, f"walk-forward train {kw}", kind="search")[1]
        grid.append({"params": kw, "train_sharpe": m["sharpe"], "train_return": m["total_return"]})
    best = max(grid, key=lambda g: g["train_sharpe"])
    test = runner.run(b, BASE.with_(name="walk-forward pick", **best["params"]), f"walk-forward test {best['params']}", kind="search")[1]
    return {
        "train_period": "A",
        "test_period": "B",
        "grid": grid,
        "chosen": best["params"],
        "test": {k: test[k] for k in ("total_return", "cagr", "sharpe", "max_drawdown", "trades", "win_rate")},
    }


def readiness(report: dict, coverage: dict) -> list[dict]:
    a = report["periods"]["A"]
    b = report["periods"]["B"]
    worst = next(s for s in a["stress"] if s["label"].startswith("Worst case"))
    half = next(s for s in a["stress"] if s["label"].startswith("Half of names"))
    cap100 = next(c for c in a["capacity"] if c["capital"] == 100_000)
    priced = sum(p["metrics"]["signals"] - p["metrics"]["skipped"].get("no_price_data", 0) for p in (a, b))
    total_offerings = sum(c["offerings"] + c.get("offerings_without_ticker", 0) for c in coverage.values())
    trades = a["metrics"]["trades"] + b["metrics"]["trades"]

    def gate(name, ok, value, threshold, why, pending=False):
        return {"gate": name, "status": "pending" if pending else ("pass" if ok else "fail"), "value": value, "threshold": threshold, "why": why}

    return [
        gate("Out-of-sample Sharpe", a["metrics"]["sharpe"] >= 0.5, a["metrics"]["sharpe"], ">= 0.5",
             "Period A never touched the signal's discovery. This is the honest test."),
        gate("Out-of-sample return after costs", a["metrics"]["total_return"] > 0, a["metrics"]["total_return"], "> 0", "Must make money net of spread, slippage and borrow."),
        gate("Deflated Sharpe (A)", report["overfitting"]["dsr_A"] >= 0.95, report["overfitting"]["dsr_A"], ">= 0.95",
             f"Probability the Sharpe is real after {report['overfitting']['trials']} configurations were tried."),
        gate("Max drawdown", max(a["metrics"]["max_drawdown"], b["metrics"]["max_drawdown"]) <= 0.30,
             max(a["metrics"]["max_drawdown"], b["metrics"]["max_drawdown"]), "<= 30%", "Deeper drawdowns get abandoned or margin-called in practice."),
        gate("Survives worst-case stress (A)", worst["sharpe"] > 0, worst["sharpe"], "Sharpe > 0",
             "Costs x2, borrow 300%/yr, half the names unborrowable, two-day delay, all at once."),
        gate("Robust to random borrow luck (A)", a["monte_carlo"]["sharpe_p05"] > 0, a["monte_carlo"]["sharpe_p05"], "5th-percentile Sharpe > 0",
             "Which names happen to be borrowable or recalled is luck; the bad-luck case must still work."),
        gate("Survives limited borrow (A)", half["total_return"] > 0, half["total_return"], "return > 0", "Real borrow availability is unknown; half unborrowable is a plausible case."),
        gate("Enough trades", trades >= 100, trades, ">= 100", "Fewer trades means the result could be a handful of lucky names."),
        gate("Price-data coverage", total_offerings > 0 and priced / total_offerings >= 0.8,
             round(priced / total_offerings, 3) if total_offerings else 0, ">= 80%",
             "Offerings by companies that later delisted have no prices: survivorship bias."),
        gate("Capacity at $100k", cap100["fill_rate"] >= 0.5, cap100["fill_rate"], ">= 50% of signals filled",
             "Liquidity and price filters must leave enough tradable signals."),
        gate("Real borrow data", False, f"{report['borrow_check'].get('days', 0)} day(s) archived", ">= 90 days of IBKR snapshots + broker locates",
             "The backtest assumes borrow. The archiver now saves IBKR's daily file; refit the borrow model once there is history.", pending=True),
        gate("Paper trading", False, "not started", ">= 3 months, tracking within 30% of backtest",
             "Forward test with no money: catches execution and data problems a backtest cannot.", pending=True),
        gate("Risk controls", False, "not built", "kill switch, daily loss limit, per-name cap, locate check",
             "Required before any automated order touches a real account.", pending=True),
    ]


def verdict(gates: list[dict]) -> dict:
    research = [g for g in gates if g["status"] != "pending"]
    failed = [g["gate"] for g in research if g["status"] == "fail"]
    if failed:
        return {"level": "not_ready", "headline": "Not ready for real money",
                "detail": f"Fails {len(failed)} research gate(s): {', '.join(failed)}. Fix or abandon before paper trading."}
    return {"level": "paper_next", "headline": "Passes the research gates: next step is paper trading, not real money",
            "detail": "Borrow data, a paper-trading track record and risk controls are still missing. Each is required before live capital."}


def overfitting_block(rets_by_period: dict[str, list[float]], trials: dict[str, float]) -> dict:
    """report["overfitting"]: Deflated Sharpe per period against every distinct configuration tried.

    Also publishes the exact DSR inputs the report does not otherwise carry, so a reader (the Learn calculator) can
    recompute it: n_returns_<key> (daily returns in that period) and trial_sharpe_std (sample sd of the trial
    Sharpes, annualized; 0.0 with fewer than 2 trials, matching expected_max_sharpe).
    """
    sharpes = list(trials.values())
    overfit: dict = {"trials": len(trials)}
    for key, rets in rets_by_period.items():
        val, bench_sr = dsr(rets, sharpes)
        overfit[f"dsr_{key}"] = round(val, 3)
        overfit[f"luck_sharpe_{key}"] = round(bench_sr, 2)
        overfit[f"n_returns_{key}"] = len(rets)
    overfit["trial_sharpe_std"] = round(statistics.stdev(sharpes), 4) if len(sharpes) >= 2 else 0.0
    return overfit


def build_report() -> dict:
    s = get_settings()
    price_dir = os.path.join(s.data_dir, "prices")
    bench = load_prices("IWM", PRICE_START, PRICE_END, price_dir)
    if bench is None:
        raise SystemExit("IWM prices unavailable")
    events, coverage = {}, {}
    for key, period in PERIODS.items():
        events[key], coverage[key] = build_universe(period, s.data_dir, s.sec_user_agent)
        log.info("Period %s: %s", key, coverage[key])
    prices = {t: load_prices(t, PRICE_START, PRICE_END, price_dir) for t in {e.ticker for evs in events.values() for e in evs}}

    runner = Runner(s.data_dir, events, prices, bench)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "strategy": STRATEGY, "base_config": BASE.__dict__,
              "coverage": coverage, "periods": {}}
    for key, period in PERIODS.items():
        log.info("Running period %s", key)
        report["periods"][key] = run_period(runner, period)
        report["periods"][key]["waterfall"] = waterfall(runner, period)
        report["periods"][key]["borrow_sensitivity"] = borrow_sensitivity(runner, period)
    report["walk_forward"] = walk_forward(runner)

    # Overfitting: deflate against every distinct configuration tried, this run and before
    history = read_runs(s.data_dir)
    trials = {trial_id(r): r["metrics"]["sharpe"] for r in history if r["strategy"] == STRATEGY["id"] and is_search(r)}
    trials.update(runner.trial_sharpes)
    report["overfitting"] = overfitting_block({key: report["periods"][key].pop("_rets") for key in PERIODS}, trials)

    report["borrow_check"] = borrow_check(s.data_dir, events["B"])
    report["key_finding"] = key_finding(report)
    report["readiness"] = readiness(report, coverage)
    report["verdict"] = verdict(report["readiness"])
    report["live_projection"] = live_projection(report)
    report["assumptions"] = assumptions()
    return report


def borrow_check(data_dir: str, events: list[OfferingEvent]) -> dict:
    """Compare the backtest borrow assumptions with today's IBKR snapshot for recent issuers."""
    snap = borrow.latest(data_dir)
    st = borrow.status(data_dir)
    if not snap or not events:
        return {"available": False, **st}
    cutoff = max(e.accepted_et for e in events).date().toordinal() - 180
    tickers = sorted({e.ticker for e in events if e.accepted_et.date().toordinal() >= cutoff})
    listed = [snap[t] for t in tickers if t in snap]
    borrowable = [x for x in listed if x["available"] is None or x["available"] > 0]
    fees = sorted(x["fee_rate"] for x in borrowable if x["fee_rate"] is not None)

    def q(p: float) -> float | None:
        return round(fees[min(len(fees) - 1, int(p * len(fees)))], 4) if fees else None

    return {
        "available": True,
        **st,
        "issuers_checked": len(tickers),
        "on_ibkr_list": len(listed),
        "borrowable_share": round(len(borrowable) / len(tickers), 3) if tickers else None,
        "fee_p25": q(0.25),
        "fee_median": q(0.5),
        "fee_p75": q(0.75),
        "fee_p90": q(0.9),
        "assumed_availability": BASE.availability,
        "assumed_fee": BASE.borrow_apr,
        "note": "Today's borrow for nano caps that priced an offering in the last 6 months of period B. "
                "Fees right at an offering are likely higher, so treat these as a lower bound.",
    }


def key_finding(report: dict) -> dict:
    """One plain-English paragraph: where the edge is, what kills it, and what would settle it."""
    a, b = report["periods"]["A"], report["periods"]["B"]
    gross_a, gross_b = a["waterfall"][0], b["waterfall"][0]
    be_a, be_b = a["borrow_sensitivity"]["breakeven_apr"], b["borrow_sensitivity"]["breakeven_apr"]
    bc = report["borrow_check"]
    steps = a["waterfall"]
    drops = [(steps[i]["step"], steps[i - 1]["avg_trade_return"] - steps[i]["avg_trade_return"]) for i in range(1, len(steps))]
    worst_step, worst_drop = max(drops, key=lambda x: x[1])
    text = (
        f"The drift is real before frictions: the average short returned {gross_a['avg_trade_return']:+.1%} per trade "
        f"out-of-sample (median {gross_a['median_trade_return']:+.1%}) and {gross_b['avg_trade_return']:+.1%} in the discovery period. "
        f"The biggest single cost is '{worst_step}' ({worst_drop:.1%} per trade). "
        f"With every assumed friction the strategy loses money, so it is not tradable as specified. "
    )
    def breakeven_phrase(be: float | None, label: str) -> str:
        if be is None:
            return f"stays profitable at every borrow fee tested ({label})"
        if be == 0.0:
            return f"loses money even with free borrow ({label})"
        return f"breaks even at an average borrow fee of about {be:.0%}/yr ({label})"

    text += f"It {breakeven_phrase(be_a, 'out-of-sample')} and {breakeven_phrase(be_b, 'discovery period')}. "
    if bc.get("available") and bc.get("fee_median") is not None:
        text += (
            f"Today's IBKR file shows a median fee of {bc['fee_median']:.0%}/yr for recent nano-cap issuers "
            f"({bc['fee_p75']:.0%} at the 75th percentile), with {bc['borrowable_share']:.0%} borrowable, so the 75% assumption "
            "may be pessimistic. "
        )
    if be_a == 0.0:
        text += (
            "But cheaper borrow alone would not rescue it: the out-of-sample period fails on spread, squeeze stops, recalls "
            "and unborrowable names even at zero borrow. The edge looks strongest in the most recent years, which could be "
            "a regime change (more toxic offerings since 2023) or luck. Only fresh data can tell."
        )
    elif bc.get("available"):
        text += (
            "A fee-aware version is a new hypothesis: it needs months of archived borrow data and a pre-registered test, "
            "not a tweak to this backtest."
        )
    return {"text": text, "breakeven_apr_A": be_a, "breakeven_apr_B": be_b}


def live_projection(report: dict) -> dict:
    """What trading this with real money would plausibly look like, from the out-of-sample period."""
    a = report["periods"]["A"]
    worst = next(s for s in a["stress"] if s["label"].startswith("Worst case"))
    boot = a["bootstrap"]
    return {
        "basis": "Period A (out-of-sample), base configuration, $100k",
        "expected_annual_return_range": [boot.get("annual_return_p05"), boot.get("annual_return_p50"), boot.get("annual_return_p95")],
        "prob_losing_year": boot.get("prob_losing_year"),
        "worst_month": a["metrics"]["worst_month"],
        "max_drawdown": a["metrics"]["max_drawdown"],
        "worst_case_stress_cagr": worst["cagr"],
        "capacity": a["capacity"],
        "not_modeled": [
            "Short squeezes beyond the daily close (intraday spikes can trigger margin calls before the stop).",
            "Borrow recalls and buy-ins: lenders can take shares back at any time.",
            "Hard-to-borrow fees that change daily and can exceed 200%/yr right after an offering.",
            "Locate failures at the moment of entry; the first close after an offering is when demand to short peaks.",
            "Margin: shorts need 150%+ collateral under Reg T, and brokers raise requirements on volatile nano caps.",
            "Taxes: every trade is short-term; short dividends and fees are ordinary expenses.",
        ],
    }


def assumptions() -> list[str]:
    c = BASE
    return [
        f"Entry at the close {c.entry_delay} trading day(s) after the first close a trader could act on after EDGAR acceptance (Rule 201 often blocks shorting into the day-0 drop).",
        f"Hold {c.hold_days} trading days; cover if the close is {int((c.stop_loss or 0) * 100)}% above entry, filled {c.stop_slippage:.0%} worse.",
        f"Position size {c.position_pct:.0%} of equity, at most {c.max_adv_pct:.0%} of the 20-day median dollar volume; max {c.max_positions} positions, total shorts at most {c.max_gross_short:.0%} of equity.",
        f"Skip stocks under ${c.min_price:.2f} (unadjusted) or with under ${c.min_adv:,.0f}/day median volume before entry.",
        f"Round-trip spread and slippage {c.cost_round_trip:.1%}; borrow {c.borrow_apr:.0%}/yr on the short notional.",
        f"{1 - c.availability:.0%} of trades randomly unborrowable; {c.recall_prob:.0%}/day chance of a recall, covered {c.recall_penalty:.0%} worse.",
        f"If price data ends (delisting or halt), cover at the last price +{c.delist_penalty:.0%}: no credit for the delisting.",
        "Each short is hedged with an equal long position in IWM (about 0.04% round trip).",
        "Size from SEC public float measured before each period (Q2 2020 for A, Q2 2023 for B).",
        "Prices: Yahoo adjusted closes; delisted names without data are excluded and counted under coverage.",
        "Risk-free rate is zero and short proceeds earn no interest (conservative; brokers pay some rebate on large accounts).",
    ]


def save(report: dict) -> str:
    s = get_settings()
    out_dir = os.path.join(s.data_dir, "backtests")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "report_latest.json")
    from app.research_jobs import atomic_json
    atomic_json(path, report)
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = build_report()
    path = save(report)
    for key, p in report["periods"].items():
        m = p["metrics"]
        log.info("%s %s: return %+.1f%%, CAGR %+.1f%%, Sharpe %.2f, maxDD %.1f%%, trades %d of %d signals",
                 key, p["period"]["role"], 100 * m["total_return"], 100 * m["cagr"], m["sharpe"],
                 100 * m["max_drawdown"], m["trades"], m["signals"])
    log.info("Overfitting: %s", report["overfitting"])
    log.info("Walk-forward: chose %s, test %s", report["walk_forward"]["chosen"], report["walk_forward"]["test"])
    for g in report["readiness"]:
        log.info("[%s] %s: %s (%s)", g["status"].upper(), g["gate"], g["value"], g["threshold"])
    log.info("Verdict: %s", report["verdict"]["headline"])
    log.info("Wrote %s", path)


if __name__ == "__main__":
    main()
