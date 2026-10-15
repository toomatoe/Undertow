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
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx

log = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_MIN_INTERVAL = 0.35  # seconds between network requests
_last_request = 0.0


@dataclass
class PriceSeries:
    symbol: str
    dates: list[date]
    close: list[float]  # split- and dividend-adjusted

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
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    dates, closes = [], []
    for ts, px in zip(stamps, adj):
        if px is None or px <= 0:
            continue
        dates.append(datetime.fromtimestamp(ts, tz=timezone.utc).date())
        closes.append(float(px))
    return PriceSeries(symbol, dates, closes) if dates else None


def load_prices(ticker: str, start: date, end: date, cache_dir: str) -> PriceSeries | None:
    """Adjusted daily closes, from cache when present. None if the symbol has no data."""
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
            log.warning("Rate limited by Yahoo; backing off 30s")
            time.sleep(30)
            return load_prices(ticker, start, end, cache_dir)
        payload = resp.json() if resp.status_code in (200, 404) else {}
        if resp.status_code in (200, 404):  # cache misses too, so reruns don't re-ask
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
    return parse_chart(ticker, payload)
