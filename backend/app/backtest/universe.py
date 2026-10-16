"""Point-in-time event universe: every priced offering by a nano-cap company in a period.

Unlike the event study (a random sample), the backtest uses the whole
population so the strategy sees every trade it would have taken.

- Size is the SEC public float measured at end of Q2 of `float_year`, before
  the period starts, so a company's eligibility never uses future information.
- Events are 424B4/424B5 filings timed by EDGAR acceptance time.
- Companies that have since delisted are kept in the universe; they drop out
  only when no price history can be found, and that loss is counted.
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime

from app.pipeline.companies import fetch_frame
from app.research.eventstudy import ET, EXCLUDED_SIC, SUBMISSIONS_URL, filings_table, get_json

log = logging.getLogger(__name__)

OFFERING_FORMS = {"424B4", "424B5"}


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    role: str  # "out_of_sample" | "discovery"
    float_year: int
    start: date
    end: date


PERIODS = {
    "A": Period("A", "Oct 2020 – Aug 2023", "out_of_sample", 2020, date(2020, 10, 1), date(2023, 8, 31)),
    "B": Period("B", "Oct 2023 – Aug 2026", "discovery", 2023, date(2023, 10, 1), date(2026, 8, 31)),
}


@dataclass(frozen=True)
class OfferingEvent:
    cik: int
    ticker: str
    company: str
    form: str
    accepted_et: datetime
    accession: str
    public_float: float

    @property
    def filing_url(self) -> str:
        acc = self.accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{acc}/{self.accession}-index.htm"


def build_universe(
    period: Period, data_dir: str, user_agent: str, max_float: float = 50e6
) -> tuple[list[OfferingEvent], dict]:
    floats = fetch_frame(period.float_year, data_dir, user_agent, max_age=float("inf"))
    ciks = sorted(cik for cik, rec in floats.items() if 0 < rec.public_float < max_float)
    cache_dir = os.path.join(data_dir, "submissions")
    coverage = {"companies_in_size_range": len(ciks), "not_operating": 0, "no_ticker": 0, "companies_with_offerings": 0}
    events: list[OfferingEvent] = []
    for i, cik in enumerate(ciks):
        cache = os.path.join(cache_dir, f"{cik}.json")
        if not os.path.exists(cache):
            time.sleep(0.12)  # SEC fair access
        sub = get_json(SUBMISSIONS_URL.format(cik=cik), user_agent, cache)
        if i and i % 250 == 0:
            log.info("%s: scanned %d/%d companies, %d offerings so far", period.key, i, len(ciks), len(events))
        if sub is None:
            continue
        if sub.get("entityType") != "operating" or str(sub.get("sic")) in EXCLUDED_SIC:
            coverage["not_operating"] += 1
            continue
        found = []
        for row in filings_table(sub, user_agent):
            if row["form"] not in OFFERING_FORMS:
                continue
            accepted = datetime.fromisoformat(row["accepted"].replace("Z", "+00:00")).astimezone(ET)
            if period.start <= accepted.date() <= period.end:
                found.append((row, accepted))
        if not found:
            continue
        tickers = sub.get("tickers") or []
        if not tickers:
            coverage["no_ticker"] += 1  # delisted or never listed: no prices available
            coverage.setdefault("offerings_without_ticker", 0)
            coverage["offerings_without_ticker"] += len(found)
            continue
        coverage["companies_with_offerings"] += 1
        for row, accepted in found:
            events.append(
                OfferingEvent(
                    cik=cik,
                    ticker=tickers[0].upper(),
                    company=sub.get("name", ""),
                    form=row["form"],
                    accepted_et=accepted,
                    accession=row["accession"],
                    public_float=floats[cik].public_float,
                )
            )
    events.sort(key=lambda e: e.accepted_et)
    coverage["offerings"] = len(events)
    return events, coverage


# One price window for every backtest run, so the on-disk cache is shared
PRICE_START = date(2020, 9, 1)
PRICE_END = date(2026, 10, 10)
