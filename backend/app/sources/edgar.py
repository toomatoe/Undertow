"""SEC EDGAR "latest filings" Atom feed, filtered to 8-Ks (material events)."""

import re

import feedparser
import httpx

from app.pipeline.tickers import TickerUniverse
from app.sources.base import RawArticle
from app.sources.rss import clean_html, entry_published

FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K"
    "&company=&dateb=&owner=include&count=100&output=atom"
)

# "8-K - Apple Inc. (0000320193) (Filer)"
_TITLE_RE = re.compile(r"^(?P<form>[\w/-]+)\s+-\s+(?P<company>.+?)\s+\((?P<cik>\d{10})\)")
_ITEM_RE = re.compile(r"Item\s+(\d\.\d{2})")

# 8-K item number -> our event taxonomy (see pipeline.enrich.EVENT_TYPES)
ITEM_EVENTS = {
    "1.01": "deal",
    "1.03": "bankruptcy",
    "2.01": "m&a",
    "2.02": "earnings",
    "2.05": "restructuring",
    "2.06": "impairment",
    "3.01": "listing",
    "4.02": "accounting",
    "5.02": "management",
    "7.01": "disclosure",
    "8.01": "other",
}


def parse_items(summary: str | None) -> list[str]:
    return _ITEM_RE.findall(summary or "")


def event_from_items(items: list[str]) -> str | None:
    for item in items:  # first mapped item wins; earlier items are usually more material
        if item in ITEM_EVENTS and ITEM_EVENTS[item] != "other":
            return ITEM_EVENTS[item]
    return "other" if items else None


class EdgarSource:
    name = "SEC EDGAR 8-K"

    def __init__(self, user_agent: str, universe: TickerUniverse):
        self.user_agent = user_agent
        self.universe = universe

    def fetch(self) -> list[RawArticle]:
        resp = httpx.get(FEED_URL, headers={"User-Agent": self.user_agent}, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        articles = []
        for entry in feed.entries:
            m = _TITLE_RE.match(entry.get("title", ""))
            if not m or m["form"] not in ("8-K", "8-K/A"):
                continue
            items = parse_items(entry.get("summary"))
            company = m["company"].strip()
            tickers = {(t, "edgar") for t in self.universe.tickers_for_cik(int(m["cik"]))}
            item_text = ", ".join(items) if items else "n/a"
            articles.append(
                RawArticle(
                    url=entry.get("link"),
                    title=f"{m['form']}: {company} (items {item_text})",
                    published_at=entry_published(entry),
                    source="edgar",
                    source_name=self.name,
                    snippet=clean_html(entry.get("summary")),
                    tickers=tickers,
                    event_type=event_from_items(items),
                )
            )
        return articles
