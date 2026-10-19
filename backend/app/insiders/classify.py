"""Routine vs opportunistic insiders (Cohen, Malloy & Pomorski 2012), as pre-registered.

For a purchase in calendar year Y, look at the insider's trades (code P or S) with a transaction date in
Y-3, Y-2 and Y-1 that were filed on or before the event's filing date (point in time):

- fewer than one trade in any of those 3 years -> unclassified (None);
- a calendar month with a trade in each of the 3 years -> "routine";
- otherwise -> "opportunistic".

Pure functions over (insider_cik, trade dates); TradeHistory only indexes them.
"""

import bisect
from collections import defaultdict
from datetime import date
from typing import Iterable

ROUTINE = "routine"
OPPORTUNISTIC = "opportunistic"
LOOKBACK_YEARS = 3
HISTORY_CODES = ("P", "S")


def classify_trades(trade_dates: Iterable[date], year: int) -> str | None:
    """CMP class for a trade in `year`, given the insider's other trade dates (any years)."""
    prior = range(year - LOOKBACK_YEARS, year)
    months: dict[int, set[int]] = {y: set() for y in prior}
    for d in trade_dates:
        if d is not None and d.year in months:
            months[d.year].add(d.month)
    if any(not months[y] for y in prior):
        return None
    common = set.intersection(*(months[y] for y in prior))
    return ROUTINE if common else OPPORTUNISTIC


class TradeHistory:
    """Every insider's (filing_date, trade_date) pairs, queried point in time."""

    def __init__(self) -> None:
        self._trades: dict[int, list[tuple[date, date]]] = defaultdict(list)
        self._sorted = True

    def add(self, insider_cik: int, trade_date: date | None, filing_date: date | None) -> None:
        if trade_date is None or filing_date is None:
            return
        self._trades[insider_cik].append((filing_date, trade_date))
        self._sorted = False

    def _sort(self) -> None:
        if not self._sorted:
            for v in self._trades.values():
                v.sort()
            self._sorted = True

    def trade_dates(self, insider_cik: int, as_of: date) -> list[date]:
        """Trade dates of the insider's trades filed on or before as_of."""
        self._sort()
        trades = self._trades.get(insider_cik, [])
        k = bisect.bisect_right(trades, (as_of, date.max))
        return [t for _, t in trades[:k]]

    def classify(self, insider_cik: int, year: int, as_of: date) -> str | None:
        return classify_trades(self.trade_dates(insider_cik, as_of), year)

    def __len__(self) -> int:
        return sum(len(v) for v in self._trades.values())
