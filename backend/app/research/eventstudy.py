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
- Short trades also pay an estimated borrow fee (BORROW_APR), since small caps
  are often hard to borrow. Real fees can be far higher, or shares unavailable.
- Baseline: the same companies measured on ordinary days (every BASELINE_STEP
  trading days). Small caps can lag the index on any day, so a signal must
  beat the baseline, not just zero, to show the filing carries information.
- Abnormal returns are winsorized at the 1st/99th percentile per bucket.
- Significance: Bonferroni across every (signal, bucket, horizon) test with
  n >= MIN_N. A result must be significant vs zero AND vs the baseline, point
  the expected way, and clear costs and borrow.

Reporting-only additions (2026-10-19, no change to the design or to `significant`):
- Each results row also carries `t_stat_clustered` and `t_vs_baseline_clustered`
  (firm-clustered CR1 t-stats, clusters = companies) and `clusters`. They show how
  much non-independent events inflate the plain t; `significant` still uses the
  plain `t_stat` / Welch `t_vs_baseline`.
- `config.study` / `config.design` name the StudyDesign; `inputs_manifest` points at
  a hash-only manifest of the cache files the run read (app.research.snapshot).

Other studies reuse this machinery through StudyDesign + run_design() (out of sample:
app.research.oos; insider Form 4 study: app.insiders.study, via summarize(signal_defs=...)).

Run:  python -m app.research.eventstudy [--nano 150 --micro 250 --small 250 --large 100]
                                        [--offline [--allow-missing]] [--output PATH]
"""

import argparse
import bisect
import hashlib
import json
import logging
import math
import os
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings
from app.pipeline.companies import bucket_for, fetch_frame
from app.pipeline.signals import ALL_SIGNALS, SignalDef, signals_for_filing
from app.research import snapshot
from app.research.prices import PriceSeries, load_prices

log = logging.getLogger("eventstudy")

RESULTS_FILE = "event_study.json"
FLOAT_YEAR = 2023  # size measured at end of Q2 2023
WINDOW_START = date(2023, 10, 1)
WINDOW_END = date(2026, 8, 31)  # leaves room for 20 trading days of drift
SEED = 7
DEFAULT_SIZES = {"nano": 150, "micro": 250, "small": 250, "large": 100}
HORIZONS = [5, 20]
MIN_N = 20
COSTS = {"nano": 0.03, "micro": 0.015, "small": 0.005, "mid": 0.002, "large": 0.001}
BORROW_APR = {"nano": 0.50, "micro": 0.25, "small": 0.05, "mid": 0.01, "large": 0.005}
BASELINE = "baseline"
BASELINE_STEP = 21  # one ordinary-day observation per company per ~month
BENCHMARK = {"nano": "IWM", "micro": "IWM", "small": "IWM", "mid": "IWM", "large": "SPY"}
ET = ZoneInfo("America/New_York")
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
EXCLUDED_SIC = {"6770"}  # blank-check companies (SPACs)
OFFLINE_MISS = "offline_miss"  # coverage key / company status for cache misses in --offline mode


@dataclass
class Event:
    cik: int
    ticker: str
    bucket: str
    signal: str
    accepted_et: datetime


@dataclass(frozen=True)
class StudyDesign:
    """Everything that defines one study's sample. Fix it before running (see AGENTS.md).

    exclude_ciks removes companies from the frame before sampling (e.g. the out-of-sample
    study excludes every in-sample candidate). results_file is relative to DATA_DIR.
    """

    name: str
    window_start: date
    window_end: date
    float_year: int
    seed: int
    sizes: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_SIZES))
    exclude_ciks: frozenset[int] = frozenset()
    results_file: str = RESULTS_FILE

    @property
    def window(self) -> tuple[date, date]:
        return self.window_start, self.window_end

    def to_config(self) -> dict:
        """JSON form for config.design. exclude_ciks is summarized (count + sha256 of the sorted list)."""
        excluded = sorted(self.exclude_ciks)
        return {
            "name": self.name,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "float_year": self.float_year,
            "seed": self.seed,
            "sizes": dict(self.sizes),
            "exclude_ciks": {
                "count": len(excluded),
                "sha256": hashlib.sha256(",".join(map(str, excluded)).encode()).hexdigest(),
            },
            "results_file": self.results_file,
        }


def in_sample_design(sizes: Mapping[str, int] | None = None) -> StudyDesign:
    """The original (2023-10 .. 2026-08, frame CY2023Q2, seed 7) design behind event_study.json."""
    return StudyDesign("in_sample", WINDOW_START, WINDOW_END, FLOAT_YEAR, SEED,
                       dict(DEFAULT_SIZES if sizes is None else sizes))


# --- Data collection -------------------------------------------------------------


def get_json(url: str, user_agent: str, cache_path: str | None = None, offline: bool = False) -> dict | None:
    """GET a JSON document, cached at cache_path when given (404s cached as null).

    offline=True never touches the network: an uncached document returns None and is
    recorded with snapshot.record_miss.
    """
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        snapshot.record_read(cache_path)
        return data
    if offline:
        snapshot.record_miss(cache_path or url)
        return None
    for attempt in range(3):
        try:
            resp = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30)
            if resp.status_code == 404:
                data = None
            else:
                resp.raise_for_status()
                data = resp.json()
            if cache_path:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                snapshot.record_read(cache_path)
            return data
        except httpx.HTTPError as exc:
            log.debug("Retry %s for %s: %s", attempt, url, exc)
            time.sleep(2 * (attempt + 1))
    return None


def filings_table(
    sub: dict, user_agent: str, *, window_start: date | None = None, cache_dir: str | None = None,
    offline: bool = False,
) -> list[dict]:
    """All filings from a submissions document, including older pages when needed.

    Older pages are cached under {cache_dir}/pages/ when cache_dir is given, so offline replays
    can read them too.
    """
    window_start = window_start or WINDOW_START
    rows = []

    def add(block: dict) -> None:
        for i, form in enumerate(block.get("form", [])):
            rows.append(
                {
                    "form": form,
                    "accepted": block["acceptanceDateTime"][i],
                    "filing_date": block["filingDate"][i],
                    "items": block.get("items", [""] * len(block["form"]))[i] or "",
                    "accession": block.get("accessionNumber", [""] * len(block["form"]))[i],
                }
            )

    recent = sub.get("filings", {}).get("recent", {})
    add(recent)
    oldest = min(recent.get("filingDate") or ["9999"])
    if oldest > window_start.isoformat():
        for f in sub.get("filings", {}).get("files", []):
            if f.get("filingTo", "") >= window_start.isoformat():
                cache = os.path.join(cache_dir, "pages", f["name"]) if cache_dir else None
                if not offline and not (cache and os.path.exists(cache)):
                    time.sleep(0.12)
                page = get_json(f"https://data.sec.gov/submissions/{f['name']}", user_agent, cache, offline)
                if page is not None:
                    add(page)
    return rows


def company_events(
    cik: int, bucket: str, user_agent: str, cache_dir: str | None = None, *,
    window: tuple[date, date] | None = None, offline: bool = False,
) -> tuple[str | None, list[Event], str]:
    """(ticker, events, status) for one company. status explains exclusions.

    This is the default `event_source` of run_design(). Any replacement must accept the same
    arguments and return the same tuple; status "ok" keeps the company.
    """
    start, end = window or (WINDOW_START, WINDOW_END)
    cache = os.path.join(cache_dir, f"{cik}.json") if cache_dir else None
    sub = get_json(SUBMISSIONS_URL.format(cik=cik), user_agent, cache, offline)
    if sub is None:
        if offline and not (cache and os.path.exists(cache)):
            return None, [], OFFLINE_MISS
        return None, [], "no_submissions"
    if sub.get("entityType") != "operating" or str(sub.get("sic")) in EXCLUDED_SIC:
        return None, [], "not_operating_company"
    tickers = sub.get("tickers") or []
    if not tickers:
        return None, [], "no_ticker"
    ticker = tickers[0].upper()
    events = []
    for row in filings_table(sub, user_agent, window_start=start, cache_dir=cache_dir, offline=offline):
        form = row["form"]
        if form.endswith("/A"):
            continue
        accepted = datetime.fromisoformat(row["accepted"].replace("Z", "+00:00")).astimezone(ET)
        if not (start <= accepted.date() <= end):
            continue
        items = [i.strip() for i in row["items"].split(",") if i.strip()]
        for sig in signals_for_filing(form, items):
            events.append(Event(cik, ticker, bucket, sig.code, accepted))
    return ticker, events, "ok"


def frame_path(data_dir: str, float_year: int) -> str:
    """Cache file written by pipeline.companies.fetch_frame."""
    return os.path.join(data_dir, f"public_float_CY{float_year}Q2I.json")


def sample_universe(
    sizes: Mapping[str, int], data_dir: str, user_agent: str, seed: int = SEED, *,
    float_year: int | None = None, exclude_ciks=frozenset(), offline: bool = False,
) -> dict[str, list[int]]:
    """Random candidate CIKs per bucket (2.5x oversample), deterministic for a seed.

    CIKs in exclude_ciks are removed from the frame before sampling. Offline, a missing frame
    file is recorded as a miss and nothing is sampled.
    """
    float_year = FLOAT_YEAR if float_year is None else float_year
    path = frame_path(data_dir, float_year)
    if offline and not os.path.exists(path):
        snapshot.record_miss(path)
        return {}
    floats = fetch_frame(float_year, data_dir, user_agent, max_age=float("inf"))
    if os.path.exists(path):
        snapshot.record_read(path)
    excluded = set(exclude_ciks)
    by_bucket: dict[str, list[int]] = defaultdict(list)
    for cik, rec in floats.items():
        if cik in excluded:
            continue
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


def baseline_events(
    ticker: str, cik: int, bucket: str, series: PriceSeries,
    window_start: date | None = None, window_end: date | None = None,
) -> list[Event]:
    """Ordinary-day pseudo-events: 10:00 ET every BASELINE_STEP trading days in the window."""
    start, end = window_start or WINDOW_START, window_end or WINDOW_END
    days = [d for d in series.dates if start <= d <= end]
    return [
        Event(cik, ticker, bucket, BASELINE, datetime(d.year, d.month, d.day, 10, 0, tzinfo=ET))
        for d in days[::BASELINE_STEP]
    ]


def welch_t(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    return (statistics.mean(a) - statistics.mean(b)) / se if se > 0 else 0.0


def clustered_se(values: list[float], clusters: list) -> float | None:
    """CR1 cluster-robust standard error of the mean, or None when there are fewer than 2 clusters.

    se = sqrt(G/(G-1) * sum_g (sum_{i in g} (x_i - mean))^2) / n
    With one observation per cluster this equals the plain sd / sqrt(n).
    """
    n = len(values)
    if n != len(clusters):
        raise ValueError("values and clusters must have the same length")
    sums: dict = defaultdict(float)
    mean = statistics.mean(values) if n else 0.0
    for x, g in zip(values, clusters):
        sums[g] += x - mean
    big_g = len(sums)
    if big_g < 2:
        return None
    return math.sqrt(big_g / (big_g - 1) * sum(s * s for s in sums.values())) / n


def clustered_t(values: list[float], clusters: list) -> float:
    """Firm-clustered (CR1) t of the mean vs zero. 0 when there are fewer than 2 clusters or no spread."""
    se = clustered_se(values, clusters)
    return statistics.mean(values) / se if se else 0.0


def clustered_welch_t(a: list[float], ca: list, b: list[float], cb: list) -> float:
    """(mean a - mean b) / sqrt(se_a^2 + se_b^2), each SE clustered (CR1).

    Approximation: event and baseline samples usually share companies, and their covariance is
    ignored. 0 when either side has fewer than 2 clusters or the combined SE is 0.
    """
    se_a, se_b = clustered_se(a, ca), clustered_se(b, cb)
    if se_a is None or se_b is None:
        return 0.0
    se = math.sqrt(se_a**2 + se_b**2)
    return (statistics.mean(a) - statistics.mean(b)) / se if se > 0 else 0.0


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


def winsor_bounds(measurements: list[dict]) -> dict[tuple[str, str], tuple[float, float]]:
    """1st/99th percentile per (bucket, field) over every measurement in the bucket (events + baseline)."""
    bounds: dict[tuple[str, str], tuple[float, float]] = {}
    for bucket in {m["bucket"] for m in measurements}:
        for fld in ["reaction", *[f"drift_{h}" for h in HORIZONS]]:
            vals = sorted(m[fld] for m in measurements if m["bucket"] == bucket)
            bounds[(bucket, fld)] = (percentile(vals, 0.01), percentile(vals, 0.99))
    return bounds


def summarize(measurements: list[dict], signal_defs: Mapping[str, SignalDef] | None = None) -> tuple[list[dict], dict]:
    """(results rows, testing block) for every (signal, bucket) with n >= MIN_N, at each horizon.

    Stable API (the insider study imports it): measurements are dicts from measure() with keys
    signal, bucket, ticker, reaction, drift_<h>; signal BASELINE rows form the baseline.
    signal_defs maps signal code -> SignalDef (label, direction); defaults to pipeline ALL_SIGNALS.

    `significant` uses the plain t_stat and Welch t_vs_baseline against the full-grid Bonferroni
    t_crit. t_stat_clustered / t_vs_baseline_clustered (clusters = companies) are reporting only.
    """
    signal_defs = ALL_SIGNALS if signal_defs is None else signal_defs
    bounds = winsor_bounds(measurements)

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in measurements:
        groups[(m["signal"], m["bucket"])].append(m)

    baseline: dict[tuple[str, int], list[float]] = {}
    baseline_clusters: dict[str, list[str]] = {}
    baseline_summary: dict[str, dict] = {}
    for (signal, bucket), ms in groups.items():
        if signal != BASELINE:
            continue
        baseline_summary[bucket] = {"n": len(ms)}
        baseline_clusters[bucket] = [m["ticker"] for m in ms]
        for h in HORIZONS:
            fld = f"drift_{h}"
            vals = winsorize([m[fld] for m in ms], *bounds[(bucket, fld)])
            baseline[(bucket, h)] = vals
            baseline_summary[bucket][f"mean_{h}"] = round(statistics.mean(vals), 5)

    raw_results = []
    for (signal, bucket), ms in groups.items():
        if len(ms) < MIN_N or signal == BASELINE:
            continue
        sig = signal_defs[signal]
        sign = -1 if sig.direction == "-" else 1
        cost = COSTS[bucket]
        reaction = winsorize([m["reaction"] for m in ms], *bounds[(bucket, "reaction")])
        tickers = [m["ticker"] for m in ms]
        companies = len(set(tickers))
        for h in HORIZONS:
            fld = f"drift_{h}"
            drift = winsorize([m[fld] for m in ms], *bounds[(bucket, fld)])
            mean = statistics.mean(drift)
            base = baseline.get((bucket, h), [])
            borrow = BORROW_APR[bucket] * h / 252 if sign < 0 else 0.0
            raw_results.append(
                {
                    "signal": signal,
                    "label": sig.label,
                    "direction": sig.direction,
                    "bucket": bucket,
                    "horizon_days": h,
                    "n": len(ms),
                    "companies": companies,
                    "mean_reaction": round(statistics.mean(reaction), 5),
                    "mean_abnormal": round(mean, 5),
                    "median_abnormal": round(statistics.median(drift), 5),
                    "t_stat": round(t_stat(drift), 2),
                    "hit_rate": round(sum(1 for v in drift if sign * v > cost + borrow) / len(drift), 3),
                    "cost": round(cost + borrow, 5),
                    "borrow": round(borrow, 5),
                    "mean_net": round(sign * mean - cost - borrow, 5),
                    "baseline_mean": round(statistics.mean(base), 5) if base else None,
                    "excess_vs_baseline": round(mean - statistics.mean(base), 5) if base else None,
                    "t_vs_baseline": round(welch_t(drift, base), 2) if base else None,
                    # Reporting only: firm-clustered t-stats (not used by `significant`)
                    "t_stat_clustered": round(clustered_t(drift, tickers), 2),
                    "t_vs_baseline_clustered": (
                        round(clustered_welch_t(drift, tickers, base, baseline_clusters[bucket]), 2) if base else None
                    ),
                    "clusters": companies,
                }
            )

    n_tests = len(raw_results)
    t_crit = statistics.NormalDist().inv_cdf(1 - 0.05 / (2 * max(n_tests, 1)))
    for r in raw_results:
        excess = r["excess_vs_baseline"] or 0.0
        negative = r["direction"] == "-"
        expected_way = r["direction"] == "?" or ((r["mean_abnormal"] < 0) == negative and (excess < 0) == negative)
        beats_baseline = r["t_vs_baseline"] is not None and abs(r["t_vs_baseline"]) >= t_crit
        r["significant"] = abs(r["t_stat"]) >= t_crit and beats_baseline and expected_way and r["mean_net"] > 0
        r["nominal_significant"] = abs(r["t_stat"]) >= 1.96
    raw_results.sort(key=lambda r: (r["bucket"], r["signal"], r["horizon_days"]))
    return raw_results, {"n_tests": n_tests, "t_critical": round(t_crit, 2), "baseline": baseline_summary}


# --- Main ------------------------------------------------------------------------

EventSource = Callable[..., tuple[str | None, list[Event], str]]


def price_window(design: StudyDesign) -> tuple[date, date]:
    """Price history requested per ticker (also the price cache file name)."""
    return design.window_start - timedelta(days=15), design.window_end + timedelta(days=60)


def collect(
    design: StudyDesign, event_source: EventSource | None = None, *, offline: bool = False,
    data_dir: str | None = None, user_agent: str | None = None,
) -> tuple[list[dict], dict]:
    """(measurements, coverage) for a design: sample, fetch events and prices, measure.

    event_source(cik, bucket, user_agent, cache_dir, window=(start, end), offline=bool) returns
    (ticker, events, status); defaults to company_events.
    """
    settings = get_settings()
    ua = user_agent or settings.sec_user_agent
    data_dir = data_dir or settings.data_dir
    event_source = event_source or company_events
    price_dir = os.path.join(data_dir, "prices")
    p_start, p_end = price_window(design)
    sizes = dict(design.sizes)

    benches = {s: load_prices(s, p_start, p_end, price_dir, offline=offline) for s in sorted(set(BENCHMARK.values()))}
    if any(b is None for b in benches.values()):
        for path in snapshot.misses():
            log.error("missing: %s", path)
        raise SystemExit("Benchmark prices unavailable" + (" in the offline cache" if offline else "") + "; cannot run study")

    candidates = sample_universe(sizes, data_dir, ua, design.seed, float_year=design.float_year,
                                 exclude_ciks=design.exclude_ciks, offline=offline)
    coverage = {}
    measurements: list[dict] = []
    for bucket, ciks in candidates.items():
        stats = defaultdict(int)
        kept = 0
        for cik in ciks:
            if kept >= sizes[bucket]:
                break
            if not offline:
                time.sleep(0.12)  # SEC fair access
            ticker, events, status = event_source(cik, bucket, ua, os.path.join(data_dir, "submissions"),
                                                  window=design.window, offline=offline)
            stats[status] += 1
            if status != "ok":
                continue
            kept += 1
            misses_before = len(snapshot.misses())
            series = load_prices(ticker, p_start, p_end, price_dir, offline=offline)
            if series is None and len(snapshot.misses()) > misses_before:
                stats[OFFLINE_MISS] += 1
            if series is None or len(series) < 30:
                stats["no_prices"] += 1  # mostly delisted: the survivorship hole
                continue
            stats["with_prices"] += 1
            stats["events"] += len(events)
            for ev in events + baseline_events(ticker, cik, bucket, series, *design.window):
                if (m := measure(ev, series, benches[BENCHMARK[bucket]])) is not None:
                    measurements.append(m)
                    stats["baseline_obs" if ev.signal == BASELINE else "measured_events"] += 1
        coverage[bucket] = dict(stats, companies=kept)
        log.info("%s: %s", bucket, coverage[bucket])
    return measurements, coverage


def caveats(design: StudyDesign) -> list[str]:
    return [
        f"Survivorship bias: companies delisted since {design.float_year} lose their ticker (coverage.no_ticker) or price history (coverage.no_prices), so they are missing. "
        "Missing names skew toward bad outcomes, so negative drift is likely understated, but those are also the hardest names to short.",
        "Borrow fees are a flat estimate per size bucket. Hard-to-borrow small caps after offerings can cost far more, or have no shares to borrow at all.",
        "Market-adjusted returns (stock minus index) ignore beta and other factors.",
        "Entry at the day-0 close assumes you can trade at the close; real fills in illiquid names are worse.",
        "Events from the same company or week are not independent, so t-stats are somewhat overstated.",
        f"One sample, one period (late {design.window_start.year} to {design.window_end.year}). A result here is a lead to test out of sample, not a strategy.",
        "t_stat_clustered and t_vs_baseline_clustered cluster by company (CR1) and are reporting only: `significant` uses the unclustered t-stats. "
        "The clustered baseline comparison ignores that events and baseline share companies, so it is approximate.",
    ]


def build_study(
    design: StudyDesign, measurements: list[dict], coverage: dict,
    signal_defs: Mapping[str, SignalDef] | None = None,
) -> dict:
    results, testing = summarize(measurements, signal_defs)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "window": [design.window_start.isoformat(), design.window_end.isoformat()],
            "size_measured": f"SEC public float, CY{design.float_year}Q2",
            "sample_sizes": dict(design.sizes),
            "horizons": HORIZONS,
            "min_n": MIN_N,
            "costs_round_trip": COSTS,
            "borrow_apr_for_shorts": BORROW_APR,
            "baseline_step_days": BASELINE_STEP,
            "benchmark": BENCHMARK,
            "price_source": "Yahoo Finance chart API (adjusted closes), personal research use",
            "study": design.name,
            "design": design.to_config(),
        },
        "coverage": coverage,
        "measured_events": sum(1 for m in measurements if m["signal"] != BASELINE),
        "testing": testing,
        "results": results,
        "caveats": caveats(design),
    }


def run_design(
    design: StudyDesign, event_source: EventSource | None = None,
    signal_defs: Mapping[str, SignalDef] | None = None, *, offline: bool = False,
    data_dir: str | None = None, user_agent: str | None = None,
) -> dict:
    """Run one study design end to end and return the results document (not written to disk)."""
    measurements, coverage = collect(design, event_source, offline=offline, data_dir=data_dir, user_agent=user_agent)
    return build_study(design, measurements, coverage, signal_defs)


def run(sizes: dict[str, int]) -> dict:
    """The in-sample study (in_sample_design) with the given sample sizes."""
    return run_design(in_sample_design(sizes))


def check_offline_misses(allow_missing: bool) -> None:
    """Exit non-zero listing every offline cache miss, unless allow_missing."""
    missed = snapshot.misses()
    if not missed:
        return
    level = log.warning if allow_missing else log.error
    level("%d offline cache misses:", len(missed))
    for path in missed:
        level("  missing: %s", path)
    if not allow_missing:
        raise SystemExit(f"{len(missed)} offline cache misses (rerun with --allow-missing to accept them)")


def write_study(study: dict, path: str, data_dir: str) -> str:
    """Write results atomically, then a hash-only input manifest, and point the results at it."""
    from app.research_jobs import atomic_json

    atomic_json(path, study)
    study["inputs_manifest"] = snapshot.write_manifest(data_dir, path)
    atomic_json(path, study)
    return study["inputs_manifest"]


def add_replay_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--offline", action="store_true", help="read caches only; never touch the network")
    parser.add_argument("--allow-missing", action="store_true", help="with --offline: accept cache misses")
    parser.add_argument("--output", default=None, help="results path (default {DATA_DIR}/<design results_file>)")


def log_highlights(study: dict) -> None:
    for r in study["results"]:
        if r["significant"] or r["nominal_significant"]:
            log.info(
                "%-6s %-24s h=%-2d n=%-4d drift=%+.2f%% base=%+.2f%% excess=%+.2f%% (t=%+.2f) net=%+.2f%% t=%+.2f tc=%+.2f %s",
                r["bucket"], r["signal"], r["horizon_days"], r["n"], 100 * r["mean_abnormal"],
                100 * (r["baseline_mean"] or 0), 100 * (r["excess_vs_baseline"] or 0), r["t_vs_baseline"] or 0,
                100 * r["mean_net"], r["t_stat"], r["t_stat_clustered"],
                "SIGNIFICANT" if r["significant"] else "(nominal only)",
            )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for bucket, default in DEFAULT_SIZES.items():
        parser.add_argument(f"--{bucket}", type=int, default=default)
    add_replay_args(parser)
    args = parser.parse_args(argv)
    sizes = {b: getattr(args, b) for b in DEFAULT_SIZES if getattr(args, b) > 0}
    design = in_sample_design(sizes)
    data_dir = get_settings().data_dir
    snapshot.start_tracking()
    try:
        study = run_design(design, offline=args.offline)
        check_offline_misses(args.allow_missing)
        if args.offline:
            study["offline_misses"] = len(snapshot.misses())
        path = args.output or os.path.join(data_dir, design.results_file)
        manifest = write_study(study, path, data_dir)
    finally:
        snapshot.stop_tracking()
    log.info("Wrote %s (manifest %s): %d events, %d results", path, manifest, study["measured_events"], len(study["results"]))
    log_highlights(study)


if __name__ == "__main__":
    main()
