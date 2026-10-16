"""Daily price history for research, cached on disk.

Source: Yahoo Finance's public chart endpoint. It is unofficial and its terms
restrict commercial use, so this is for personal research only: requests are
throttled and cached, and nothing is redistributed. Swap in a licensed feed
(Alpaca SIP, Databento, Massive) before anything public.

Known limitation: Yahoo mostly drops delisted tickers, so studies built on it
have survivorship bias. The event study measures and reports how much.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import httpx

log = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_MIN_INTERVAL = 0.35  # seconds between network requests
_RETRY_BACKOFF = (30, 60, 120)  # seconds to wait after each 429 before retrying
_last_request = 0.0


@dataclass
class PriceSeries:
    symbol: str
    dates: list[date]
    close: list[float]  # split- and dividend-adjusted (use for returns)
    raw_close: list[float] = field(default_factory=list)  # price actually printed that day (pre-split)
    dollar_volume: list[float] = field(default_factory=list)  # close x volume, split-invariant

    def __len__(self) -> int:
        return len(self.dates)


def yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def _throttle() -> None:
    global _last_request
    wait = _last_request + _MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def parse_chart(symbol: str, payload: dict) -> PriceSeries | None:
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    r = result[0]
    stamps = r.get("timestamp") or []
    indicators = r.get("indicators") or {}
    adj = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    quote = (indicators.get("quote") or [{}])[0]
    split_close = quote.get("close") or [None] * len(stamps)  # split-adjusted, not dividend-adjusted
    volume = quote.get("volume") or [None] * len(stamps)
    # Yahoo back-adjusts for splits; undo it to recover the price that printed on each day.
    # A 1-for-10 reverse split (numerator 1, denominator 10) multiplies earlier prices by 10.
    splits = sorted(
        (int(ts), s["numerator"] / s["denominator"])
        for ts, s in ((r.get("events") or {}).get("splits") or {}).items()
        if s.get("numerator") and s.get("denominator")
    )
    dates, closes, raw, dvol = [], [], [], []
    for ts, px, c, v in zip(stamps, adj, split_close, volume):
        if px is None or px <= 0:
            continue
        factor = 1.0
        for split_ts, ratio in splits:
            if split_ts > ts:
                factor *= ratio
        dates.append(datetime.fromtimestamp(ts, tz=timezone.utc).date())
        closes.append(float(px))
        raw.append(float(c) * factor if c else float(px) * factor)
        dvol.append(float(c) * float(v) if c and v else 0.0)
    return PriceSeries(symbol, dates, closes, raw, dvol) if dates else None


def load_prices(ticker: str, start: date, end: date, cache_dir: str, _attempt: int = 0) -> PriceSeries | None:
    """Adjusted daily closes, from cache when present. None if the symbol has no data
    (or Yahoo still rate-limits after len(_RETRY_BACKOFF) retries)."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{ticker}_{start}_{end}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    else:
        _throttle()
        params = {
            "period1": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
            "period2": int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()),
            "interval": "1d",
            "events": "split,div",
            "includeAdjustedClose": "true",
        }
        try:
            resp = httpx.get(
                CHART_URL.format(symbol=yahoo_symbol(ticker)),
                params=params,
                headers={"User-Agent": "Mozilla/5.0 (research; quantdesk)"},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            log.warning("Price request failed for %s: %s", ticker, exc)
            return None
        if resp.status_code == 429:
            if _attempt >= len(_RETRY_BACKOFF):
                log.warning("Rate limited by Yahoo; giving up on %s", ticker)
                return None
            delay = _RETRY_BACKOFF[_attempt]
            log.warning("Rate limited by Yahoo; backing off %ss", delay)
            time.sleep(delay)
            return load_prices(ticker, start, end, cache_dir, _attempt + 1)
        payload = resp.json() if resp.status_code in (200, 404) else {}
        if resp.status_code in (200, 404):  # cache misses too, so reruns don't re-ask
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
    return parse_chart(ticker, payload)
