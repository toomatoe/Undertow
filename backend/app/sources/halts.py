"""Nasdaq Trader trade-halt RSS feed (covers Nasdaq, NYSE and other US listings).

Free, no key, refreshed about every minute (ttl=1). Each item has halt date/time
(ET), symbol, name, market, reason code and resumption times.
"""

import re
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.research.eventstudy import ET

FEED_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"

# Most common codes, in plain English. Full list: nasdaqtrader.com/Trader.aspx?id=TradeHaltCodes
REASONS = {
    "T1": "News pending",
    "T2": "News released",
    "T3": "News and resumption times",
    "T5": "Single-stock trading pause (price move)",
    "T6": "Extraordinary market activity",
    "T7": "Quotation-only period",
    "T8": "ETF halt",
    "T12": "Additional information requested by the exchange",
    "H4": "Non-compliance with listing rules",
    "H9": "Not current in required filings",
    "H10": "SEC trading suspension",
    "H11": "Regulatory concern",
    "LUDP": "Volatility pause (limit up/limit down)",
    "LUDS": "Volatility pause, straddle condition",
    "MWC1": "Market-wide circuit breaker level 1",
    "MWC2": "Market-wide circuit breaker level 2",
    "MWC3": "Market-wide circuit breaker level 3",
    "M": "Volatility trading pause",
    "D": "Security deletion (delisting)",
    "IPO1": "IPO not yet trading",
}
# Halts that usually mean company news or regulatory trouble, not just a fast tape
SERIOUS = {"T1", "T2", "T3", "T12", "H4", "H9", "H10", "H11", "D"}

_FIELD = re.compile(r"<ndaq:(\w+)\s*(?:/>|>(.*?)</ndaq:\1>)", re.S)


@dataclass(frozen=True)
class Halt:
    symbol: str
    name: str
    market: str
    reason_code: str
    halted_at: datetime  # ET, tz-aware
    resumed_at: datetime | None

    @property
    def reason(self) -> str:
        return REASONS.get(self.reason_code, self.reason_code)

    @property
    def serious(self) -> bool:
        return self.reason_code in SERIOUS


def _parse_dt(day: str, clock: str) -> datetime | None:
    if not day or not clock:
        return None
    clock = clock.split(".")[0]
    try:
        return datetime.strptime(f"{day} {clock}", "%m/%d/%Y %H:%M:%S").replace(tzinfo=ET)
    except ValueError:
        return None


def parse_feed(xml: str) -> list[Halt]:
    halts = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        f = {k: (v or "").strip() for k, v in _FIELD.findall(item)}
        halted = _parse_dt(f.get("HaltDate", ""), f.get("HaltTime", ""))
        if not halted or not f.get("IssueSymbol"):
            continue
        resumed = _parse_dt(f.get("ResumptionDate", ""), f.get("ResumptionTradeTime", "")) or _parse_dt(
            f.get("ResumptionDate", ""), f.get("ResumptionQuoteTime", "")
        )
        halts.append(
            Halt(
                symbol=f["IssueSymbol"].upper(),
                name=f.get("IssueName", ""),
                market=f.get("Market", ""),
                reason_code=f.get("ReasonCode", ""),
                halted_at=halted,
                resumed_at=resumed,
            )
        )
    return halts


def fetch(user_agent: str = "Mozilla/5.0 (afterfile)") -> list[Halt]:
    resp = httpx.get(FEED_URL, headers={"User-Agent": user_agent}, timeout=20)
    resp.raise_for_status()
    return parse_feed(resp.text)
