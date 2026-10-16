"""Performance metrics and overfitting-aware statistics.

- Sharpe/Sortino use daily returns, zero risk-free rate, annualized by sqrt(252).
- PSR (Bailey & Lopez de Prado 2012): probability the true Sharpe exceeds a
  benchmark, given sample length, skew and kurtosis.
- DSR (Bailey & Lopez de Prado 2014): PSR against the Sharpe you would expect
  from the best of N trials by luck alone, so every variant tried counts.
- Stationary block bootstrap of daily returns for confidence intervals and
  the probability of a losing year.
"""

import math
import random
import statistics
from collections import defaultdict
from datetime import date

TRADING_DAYS = 252
EULER_GAMMA = 0.5772156649
_N = statistics.NormalDist()


def daily_returns(equity: list[float]) -> list[float]:
    return [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]


def sharpe(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    sd = statistics.stdev(rets)
    return statistics.mean(rets) / sd * math.sqrt(TRADING_DAYS) if sd > 0 else 0.0


def sortino(rets: list[float]) -> float:
    downside = [min(r, 0.0) for r in rets]
    dd = math.sqrt(sum(x * x for x in downside) / len(downside)) if downside else 0.0
    return statistics.mean(rets) / dd * math.sqrt(TRADING_DAYS) if dd > 0 else 0.0


def moments(rets: list[float]) -> tuple[float, float]:
    """(skewness, kurtosis) - kurtosis is the plain fourth moment (normal = 3)."""
    n = len(rets)
    if n < 4:
        return 0.0, 3.0
    m = statistics.mean(rets)
    sd = statistics.pstdev(rets)
    if sd == 0:
        return 0.0, 3.0
    skew = sum((r - m) ** 3 for r in rets) / n / sd**3
    kurt = sum((r - m) ** 4 for r in rets) / n / sd**4
    return skew, kurt


def drawdowns(equity: list[float]) -> tuple[list[float], float, int]:
    """(drawdown series, max drawdown as a positive fraction, longest drawdown in days)."""
    peak, series, longest, current = equity[0], [], 0, 0
    for e in equity:
        if e >= peak:
            peak, current = e, 0
        else:
            current += 1
        longest = max(longest, current)
        series.append(e / peak - 1 if peak > 0 else 0.0)
    return series, -min(series, default=0.0), longest


def psr(rets: list[float], benchmark_sr_annual: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio against an annualized benchmark Sharpe."""
    n = len(rets)
    if n < 10:
        return 0.0
    sd = statistics.stdev(rets)
    if sd == 0:
        return 0.0
    sr = statistics.mean(rets) / sd  # per-period
    sr_star = benchmark_sr_annual / math.sqrt(TRADING_DAYS)
    skew, kurt = moments(rets)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom <= 0:
        return 0.0
    return _N.cdf((sr - sr_star) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(trial_sharpes_annual: list[float], n_trials: int) -> float:
    """Annualized Sharpe the best of n_trials would reach by luck (zero true Sharpe)."""
    if n_trials < 2 or len(trial_sharpes_annual) < 2:
        return 0.0
    sd = statistics.stdev(trial_sharpes_annual)
    return sd * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials) + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def dsr(rets: list[float], trial_sharpes_annual: list[float]) -> tuple[float, float]:
    """(Deflated Sharpe Ratio, the luck benchmark it was deflated against)."""
    bench = expected_max_sharpe(trial_sharpes_annual, len(trial_sharpes_annual))
    return psr(rets, bench), bench


def block_bootstrap(rets: list[float], reps: int = 1000, block: int = 20, seed: int = 7) -> dict:
    """Stationary block bootstrap: Sharpe and annual return CIs, P(losing year)."""
    n = len(rets)
    if n < block * 3:
        return {}
    rng = random.Random(seed)
    sharpes, annual = [], []
    for _ in range(reps):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(n)
            length = min(int(rng.expovariate(1 / block)) + 1, n)
            sample.extend(rets[(start + k) % n] for k in range(length))
        sample = sample[:n]
        sharpes.append(sharpe(sample))
        growth = math.prod(1 + r for r in sample)
        annual.append(growth ** (TRADING_DAYS / n) - 1 if growth > 0 else -1.0)
    sharpes.sort()
    annual.sort()
    q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))]  # noqa: E731
    return {
        "sharpe_p05": round(q(sharpes, 0.05), 2),
        "sharpe_p50": round(q(sharpes, 0.50), 2),
        "sharpe_p95": round(q(sharpes, 0.95), 2),
        "annual_return_p05": round(q(annual, 0.05), 4),
        "annual_return_p50": round(q(annual, 0.50), 4),
        "annual_return_p95": round(q(annual, 0.95), 4),
        "prob_losing_year": round(sum(1 for a in annual if a < 0) / len(annual), 3),
    }


def period_returns(dates: list[date], equity: list[float], key) -> dict[str, float]:
    """Compounded return per bucket, e.g. key=lambda d: d.strftime('%Y-%m')."""
    last: dict[str, float] = {}
    first: dict[str, float] = {}
    prev = equity[0]
    for d, e in zip(dates, equity):
        k = key(d)
        first.setdefault(k, prev)
        last[k] = e
        prev = e
    return {k: round(last[k] / first[k] - 1, 4) for k in last}


def trade_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0}
    wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
    losses = [t["net_pnl"] for t in trades if t["net_pnl"] <= 0]
    reasons: dict[str, int] = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += 1
    rets = sorted(t["net_return"] for t in trades)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "avg_win": round(statistics.mean(wins), 2) if wins else 0.0,
        "avg_loss": round(statistics.mean(losses), 2) if losses else 0.0,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "avg_trade_return": round(statistics.mean(rets), 4),
        "median_trade_return": round(statistics.median(rets), 4),
        "best_trade_return": round(rets[-1], 4),
        "worst_trade_return": round(rets[0], 4),
        "avg_days_held": round(statistics.mean(t["days_held"] for t in trades), 1),
        "exit_reasons": dict(reasons),
        "total_costs": round(sum(t["costs"] for t in trades), 2),
        "total_borrow": round(sum(t["borrow"] for t in trades), 2),
    }


def summarize(dates: list[date], equity: list[float], gross: list[float], trades: list[dict]) -> dict:
    rets = daily_returns(equity)
    years = max(len(rets) / TRADING_DAYS, 1e-9)
    total = equity[-1] / equity[0] - 1 if equity else 0.0
    _, max_dd, dd_days = drawdowns(equity)
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1 if equity and equity[-1] > 0 else -1.0
    skew, kurt = moments(rets)
    return {
        "start": dates[0].isoformat() if dates else None,
        "end": dates[-1].isoformat() if dates else None,
        "start_equity": round(equity[0], 2) if equity else None,
        "end_equity": round(equity[-1], 2) if equity else None,
        "total_return": round(total, 4),
        "cagr": round(cagr, 4),
        "volatility": round(statistics.stdev(rets) * math.sqrt(TRADING_DAYS), 4) if len(rets) > 1 else 0.0,
        "sharpe": round(sharpe(rets), 2),
        "sortino": round(sortino(rets), 2),
        "max_drawdown": round(max_dd, 4),
        "longest_drawdown_days": dd_days,
        "calmar": round(cagr / max_dd, 2) if max_dd > 0 else None,
        "skew": round(skew, 2),
        "kurtosis": round(kurt, 2),
        "avg_gross_exposure": round(statistics.mean(gross), 3) if gross else 0.0,
        "time_in_market": round(sum(1 for g in gross if g > 0) / len(gross), 3) if gross else 0.0,
        "psr": round(psr(rets), 3),
        "worst_month": min(period_returns(dates, equity, lambda d: d.strftime("%Y-%m")).values(), default=0.0),
        **trade_stats(trades),
    }


def min_trl(rets: list[float], target_sr_annual: float = 0.0, confidence: float = 0.95) -> int | None:
    """Minimum track record length (days) for the observed Sharpe to beat the target at `confidence`."""
    if len(rets) < 10:
        return None
    sd = statistics.stdev(rets)
    if sd == 0:
        return None
    sr = statistics.mean(rets) / sd
    sr_star = target_sr_annual / math.sqrt(TRADING_DAYS)
    if sr <= sr_star:
        return None  # never: the observed Sharpe does not beat the target
    skew, kurt = moments(rets)
    return int(1 + (1 - skew * sr + (kurt - 1) / 4 * sr**2) * (_N.inv_cdf(confidence) / (sr - sr_star)) ** 2)
