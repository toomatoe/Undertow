"""Ticker universe (from SEC company_tickers.json) and conservative ticker tagging.

Tagging only uses high-precision signals: cashtags ($AAPL) and exchange notation
("(NASDAQ: AAPL)"). Matching bare company names produces many false positives
(Target, Visa, Apple the fruit), so that is left to the LLM enrichment step,
whose suggestions are validated against this universe.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE_MAX_AGE = 7 * 24 * 3600

_CASHTAG_RE = re.compile(r"(?<![\w$])\$([A-Z]{1,5}(?:\.[A-Z])?)\b")
_EXCHANGE_RE = re.compile(
    r"\((?:NASDAQ|Nasdaq|NasdaqGS|NasdaqGM|NasdaqCM|NYSE|NYSE American|NYSE Arca|AMEX|Cboe|OTCQX|OTCQB|OTC)"
    r"\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?(?:\s*[,;]\s*[A-Z]{1,5}(?:\.[A-Z])?)*)\)"
)


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: int
    name: str


class TickerUniverse:
    def __init__(self, companies: list[Company] | None = None):
        self.by_ticker: dict[str, Company] = {}
        self.by_cik: dict[int, list[str]] = {}
        for c in companies or []:
            self.by_ticker.setdefault(c.ticker, c)
            self.by_cik.setdefault(c.cik, []).append(c.ticker)

    def __len__(self) -> int:
        return len(self.by_ticker)

    def __contains__(self, ticker: str) -> bool:
        return ticker in self.by_ticker

    def get(self, ticker: str) -> Company | None:
        return self.by_ticker.get(ticker)

    def tickers_for_cik(self, cik: int) -> list[str]:
        # SEC lists the primary listing first; extra share classes follow
        return self.by_cik.get(cik, [])[:1]

    @classmethod
    def from_sec_json(cls, data: dict) -> "TickerUniverse":
        companies = [
            Company(ticker=row["ticker"].upper().replace("-", "."), cik=int(row["cik_str"]), name=row["title"])
            for row in data.values()
        ]
        return cls(companies)

    @classmethod
    def load(cls, data_dir: str, user_agent: str) -> "TickerUniverse":
        """Load from a local cache, refreshing from the SEC weekly. Never raises."""
        path = os.path.join(data_dir, "company_tickers.json")
        fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_MAX_AGE
        if not fresh:
            try:
                resp = httpx.get(SEC_TICKERS_URL, headers={"User-Agent": user_agent}, timeout=30)
                resp.raise_for_status()
                os.makedirs(data_dir, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(resp.content)
            except Exception as exc:  # stale cache or empty universe is fine
                log.warning("Could not refresh SEC ticker list: %s", exc)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return cls.from_sec_json(json.load(f))
        return cls()


def tag_tickers(text: str, universe: TickerUniverse) -> set[tuple[str, str]]:
    """Return {(symbol, method)} found in text. Validated against the universe when it is loaded."""
    found: set[tuple[str, str]] = set()
    candidates = [(s, "cashtag") for s in _CASHTAG_RE.findall(text)]
    for group in _EXCHANGE_RE.findall(text):  # "(NASDAQ: GOOGL, GOOG)" lists several classes
        candidates += [(s.strip(), "exchange") for s in re.split(r"[,;]", group)]
    for sym, method in candidates:
        if len(universe) == 0 or sym in universe:
            found.add((sym, method))
    return found
