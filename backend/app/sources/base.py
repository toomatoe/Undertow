from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class RawArticle:
    """Source-agnostic article, before dedupe/tagging/persistence."""

    url: str
    title: str
    published_at: datetime  # tz-aware UTC
    source: str  # rss | edgar | alpaca
    source_name: str
    snippet: str | None = None
    author: str | None = None
    # (symbol, method) pairs the source already knows about, e.g. Alpaca symbols or EDGAR CIK lookups
    tickers: set[tuple[str, str]] = field(default_factory=set)
    event_type: str | None = None


class Source(Protocol):
    name: str

    def fetch(self) -> list[RawArticle]: ...
