"""Event study: do stocks drift after SEC filing events, by company size, after costs?

Design (fixed before looking at results; changing it after seeing them is data snooping):

- Universe: operating companies (no SPACs, no funds) in the SEC public-float
  frame measured at end of Q2 2023, sampled at random per size bucket. Size is
  fixed at the start of the window, so bucket assignment has no look-ahead.
- Events: filings in app.pipeline.signals (8-K items, offerings, 13D) between
  WINDOW_START and WINDOW_END, timed by EDGAR acceptance time (UTC -> ET).
- Day 0 is the first close a trader could act on: the acceptance day if the
  filing was accepted before 15:30 ET, otherwise the next trading day.
- Reaction = day-0 return vs the previous close (mostly not tradable).
  Drift(h) = return from day-0 close to day-h close (tradable).
  Both are market-adjusted: stock return minus IWM (SPY for large caps).
- Trade direction comes from the signal's prior: "-" short, "+" and "?" long.
  Net = direction x mean drift - round-trip cost for the bucket.
  Short borrow fees, often high for small caps, are NOT modeled.
- Abnormal returns are winsorized at the 1st/99th percentile per bucket.
- Significance: Bonferroni across every (signal, bucket, horizon) test with
  n >= MIN_N. A result must also point the expected way and clear costs.

Run:  python -m app.research.eventstudy [--nano 150 --micro 250 --small 250 --large 100]
"""

import argparse
import bisect
import json
import logging
import math
import os
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.pipeline.companies import bucket_for, fetch_frame
from app.pipeline.signals import ALL_SIGNALS, signals_for_filing
from app.research.prices import PriceSeries, load_prices

log = logging.getLogger("eventstudy")

RESULTS_FILE = "event_study.json"
FLOAT_YEAR = 2023  # size measured at end of Q2 2023
WINDOW_START = date(2023, 10, 1)
WINDOW_END = date(2026, 8, 31)  # leaves room for 20 trading days of drift
HORIZONS = [5, 20]
MIN_N = 20
COSTS = {"nano": 0.03, "micro": 0.015, "small": 0.005, "mid": 0.002, "large": 0.001}
BENCHMARK = {"nano": "IWM", "micro": "IWM", "small": "IWM", "mid": "IWM", "large": "SPY"}
ET = ZoneInfo("America/New_York")
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
EXCLUDED_SIC = {"6770"}  # blank-check companies (SPACs)


@dataclass
class Event:
    cik: int
    ticker: str
    bucket: str
    signal: str
    accepted_et: datetime


# --- Data collection -------------------------------------------------------------


def get_json(url: str, user_agent: str) -> dict | None:
    for attempt in range(3):
        try:
            resp = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            log.debug("Retry %s for %s: %s", attempt, url, exc)
            time.sleep(2 * (attempt + 1))
    return None


def filings_table(sub: dict, user_agent: str) -> list[dict]:
    """All filings from a submissions document, including older pages when needed."""
    rows = []

    def add(block: dict) -> None:
        for i, form in enumerate(block.get("form", [])):
            rows.append(
                {
                    "form": form,
                    "accepted": block["acceptanceDateTime"][i],
                    "filing_date": block["filingDate"][i],
                    "items": block.get("items", [""] * len(block["form"]))[i] or "",
                }
            )

    recent = sub.get("filings", {}).get("recent", {})
    add(recent)
    oldest = min(recent.get("filingDate") or ["9999"])
    if oldest > WINDOW_START.isoformat():
        for f in sub.get("filings", {}).get("files", []):
            if f.get("filingTo", "") >= WINDOW_START.isoformat():
                time.sleep(0.12)
                if (page := get_json(f"https://data.sec.gov/submissions/{f['name']}", user_agent)) is not None:
                    add(page)
    return rows


def company_events(cik: int, bucket: str, user_agent: str) -> tuple[str | None, list[Event], str]:
    """(ticker, events, status) for one company. status explains exclusions."""
    sub = get_json(SUBMISSIONS_URL.format(cik=cik), user_agent)
    if sub is None:
        return None, [], "no_submissions"
    if sub.get("entityType") != "operating" or str(sub.get("sic")) in EXCLUDED_SIC:
        return None, [], "not_operating_company"
    tickers = sub.get("tickers") or []
    if not tickers:
        return None, [], "no_ticker"
    ticker = tickers[0].upper()
    events = []
    for row in filings_table(sub, user_agent):
        form = row["form"]
        if form.endswith("/A"):
            continue
        accepted = datetime.fromisoformat(row["accepted"].replace("Z", "+00:00")).astimezone(ET)
        if not (WINDOW_START <= accepted.date() <= WINDOW_END):
            continue
        items = [i.strip() for i in row["items"].split(",") if i.strip()]
        for sig in signals_for_filing(form, items):
            events.append(Event(cik, ticker, bucket, sig.code, accepted))
    return ticker, events, "ok"


def sample_universe(sizes: dict[str, int], data_dir: str, user_agent: str, seed: int = 7) -> dict[str, list[int]]:
    floats = fetch_frame(FLOAT_YEAR, data_dir, user_agent, max_age=float("inf"))
    by_bucket: dict[str, list[int]] = defaultdict(list)
    for cik, rec in floats.items():
        if (b := bucket_for(rec.public_float)) in sizes:
            by_bucket[b].append(cik)
    rng = random.Random(seed)
    # Oversample: SPACs, funds and dead companies get filtered out after we look them up
    return {b: rng.sample(sorted(ciks), min(len(ciks), int(sizes[b] * 2.5))) for b, ciks in by_bucket.items()}


# --- Returns ---------------------------------------------------------------------


def day0_index(series: PriceSeries, accepted_et: datetime) -> int | None:
    """Index of the first close a trader could act on after the filing."""
    d = accepted_et.date()
    if accepted_et.hour * 60 + accepted_et.minute >= 15 * 60 + 30:
        d += timedelta(days=1)
    i = bisect.bisect_left(series.dates, d)
    if i >= len(series) or i == 0 or (series.dates[i] - d).days > 5:
        return None  # no trading around the event (halt, gap in data)
    return i


def ret(series: PriceSeries, i: int, j: int) -> float:
    return series.close[j] / series.close[i] - 1


def bench_ret(bench: PriceSeries, d0: date, d1: date) -> float | None:
    i = bisect.bisect_left(bench.dates, d0)
    j = bisect.bisect_left(bench.dates, d1)
    if i >= len(bench) or j >= len(bench) or bench.dates[i] != d0 or bench.dates[j] != d1:
        return None
    return ret(bench, i, j)


def measure(event: Event, series: PriceSeries, bench: PriceSeries) -> dict | None:
    i0 = day0_index(series, event.accepted_et)
    if i0 is None:
        return None
    out = {"signal": event.signal, "bucket": event.bucket, "ticker": event.ticker}
    br = bench_ret(bench, series.dates[i0 - 1], series.dates[i0])
    if br is None:
        return None
    out["reaction"] = ret(series, i0 - 1, i0) - br
    for h in HORIZONS:
        if i0 + h >= len(series):
            return None
        br = bench_ret(bench, series.dates[i0], series.dates[i0 + h])
        if br is None:
            return None
        out[f"drift_{h}"] = ret(series, i0, i0 + h) - br
    return out


# --- Statistics ------------------------------------------------------------------


def winsorize(values: list[float], lo: float, hi: float) -> list[float]:
    return [min(max(v, lo), hi) for v in values]


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def t_stat(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    sd = statistics.stdev(values)
    return statistics.mean(values) / (sd / math.sqrt(len(values))) if sd > 0 else 0.0


def summarize(measurements: list[dict]) -> tuple[list[dict], dict]:
    # Winsorization bounds per bucket and field
    bounds: dict[tuple[str, str], tuple[float, float]] = {}
    for bucket in {m["bucket"] for m in measurements}:
        for field in ["reaction", *[f"drift_{h}" for h in HORIZONS]]:
            vals = sorted(m[field] for m in measurements if m["bucket"] == bucket)
            bounds[(bucket, field)] = (percentile(vals, 0.01), percentile(vals, 0.99))

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in measurements:
        groups[(m["signal"], m["bucket"])].append(m)

    raw_results = []
    for (signal, bucket), ms in groups.items():
        if len(ms) < MIN_N:
            continue
        sig = ALL_SIGNALS[signal]
        sign = -1 if sig.direction == "-" else 1
        cost = COSTS[bucket]
        reaction = winsorize([m["reaction"] for m in ms], *bounds[(bucket, "reaction")])
        for h in HORIZONS:
            field = f"drift_{h}"
            drift = winsorize([m[field] for m in ms], *bounds[(bucket, field)])
            mean = statistics.mean(drift)
            raw_results.append(
                {
                    "signal": signal,
                    "label": sig.label,
                    "direction": sig.direction,
                    "bucket": bucket,
                    "horizon_days": h,
                    "n": len(ms),
                    "companies": len({m["ticker"] for m in ms}),
                    "mean_reaction": round(statistics.mean(reaction), 5),
                    "mean_abnormal": round(mean, 5),
                    "median_abnormal": round(statistics.median(drift), 5),
                    "t_stat": round(t_stat(drift), 2),
                    "hit_rate": round(sum(1 for v in drift if sign * v > cost) / len(drift), 3),
                    "cost": cost,
                    "mean_net": round(sign * mean - cost, 5),
                }
            )

    n_tests = len(raw_results)
    t_crit = statistics.NormalDist().inv_cdf(1 - 0.05 / (2 * max(n_tests, 1)))
    for r in raw_results:
        expected_way = r["direction"] == "?" or (r["mean_abnormal"] < 0) == (r["direction"] == "-")
        r["significant"] = abs(r["t_stat"]) >= t_crit and expected_way and r["mean_net"] > 0
        r["nominal_significant"] = abs(r["t_stat"]) >= 1.96
    raw_results.sort(key=lambda r: (r["bucket"], r["signal"], r["horizon_days"]))
    return raw_results, {"n_tests": n_tests, "t_critical": round(t_crit, 2)}


# --- Main ------------------------------------------------------------------------


def run(sizes: dict[str, int]) -> dict:
    settings = get_settings()
    ua, data_dir = settings.sec_user_agent, settings.data_dir
    price_dir = os.path.join(data_dir, "prices")
    p_start, p_end = WINDOW_START - timedelta(days=15), WINDOW_END + timedelta(days=60)

    benches = {s: load_prices(s, p_start, p_end, price_dir) for s in set(BENCHMARK.values())}
    if any(b is None for b in benches.values()):
        raise SystemExit("Benchmark prices unavailable; cannot run study")

    candidates = sample_universe(sizes, data_dir, ua)
    coverage = {}
    measurements: list[dict] = []
    for bucket, ciks in candidates.items():
        stats = defaultdict(int)
        kept = 0
        for cik in ciks:
            if kept >= sizes[bucket]:
                break
            time.sleep(0.12)  # SEC fair access
            ticker, events, status = company_events(cik, bucket, ua)
            stats[status] += 1
            if status != "ok":
                continue
            kept += 1
            series = load_prices(ticker, p_start, p_end, price_dir)
            if series is None or len(series) < 30:
                stats["no_prices"] += 1  # mostly delisted: the survivorship hole
                continue
            stats["with_prices"] += 1
            stats["events"] += len(events)
            for ev in events:
                if (m := measure(ev, series, benches[BENCHMARK[bucket]])) is not None:
                    measurements.append(m)
                    stats["measured_events"] += 1
        coverage[bucket] = dict(stats, companies=kept)
        log.info("%s: %s", bucket, coverage[bucket])

    results, testing = summarize(measurements)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
            "size_measured": f"SEC public float, CY{FLOAT_YEAR}Q2",
            "sample_sizes": sizes,
            "horizons": HORIZONS,
            "min_n": MIN_N,
            "costs_round_trip": COSTS,
            "benchmark": BENCHMARK,
            "price_source": "Yahoo Finance chart API (adjusted closes), personal research use",
        },
        "coverage": coverage,
        "measured_events": len(measurements),
        "testing": testing,
        "results": results,
        "caveats": [
            "Survivorship bias: companies delisted since 2023 lose their ticker (coverage.no_ticker) or price history (coverage.no_prices), so they are missing. "
            "See coverage.no_prices per bucket. Missing names skew toward bad outcomes, so negative drift is likely understated.",
            "Short-borrow fees and borrow availability are not modeled. Many small caps are expensive or impossible to short.",
            "Market-adjusted returns (stock minus index) ignore beta and other factors.",
            "Entry at the day-0 close assumes you can trade at the close; real fills in illiquid names are worse.",
            "Events from the same company or week are not independent, so t-stats are somewhat overstated.",
            "One sample, one period (late 2023 to 2026). A result here is a lead to test out of sample, not a strategy.",
        ],
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for bucket, default in [("nano", 150), ("micro", 250), ("small", 250), ("large", 100)]:
        parser.add_argument(f"--{bucket}", type=int, default=default)
    args = parser.parse_args()
    sizes = {b: getattr(args, b) for b in ["nano", "micro", "small", "large"] if getattr(args, b) > 0}
    study = run(sizes)
    path = os.path.join(get_settings().data_dir, RESULTS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(study, f, indent=1)
    log.info("Wrote %s: %d events, %d results", path, study["measured_events"], len(study["results"]))
    for r in study["results"]:
        if r["significant"] or r["nominal_significant"]:
            log.info(
                "%-6s %-24s h=%-2d n=%-4d drift=%+.2f%% net=%+.2f%% t=%+.2f %s",
                r["bucket"], r["signal"], r["horizon_days"], r["n"], 100 * r["mean_abnormal"],
                100 * r["mean_net"], r["t_stat"], "SIGNIFICANT" if r["significant"] else "(nominal only)",
            )


if __name__ == "__main__":
    main()
