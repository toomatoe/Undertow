"""SEC EDGAR "latest filings" Atom feeds for event-driven forms (8-K, offerings, 13D)."""

import logging
import re
import time

import feedparser
import httpx

from app.pipeline.signals import EVENT_FORMS, signals_for_filing
from app.pipeline.tickers import TickerUniverse
from app.sources.base import RawArticle
from app.sources.rss import clean_html, entry_published

log = logging.getLogger(__name__)

FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

# "8-K - Apple Inc. (0000320193) (Filer)"  /  "SCHEDULE 13D - Target Co (0000123456) (Subject)"
_TITLE_RE = re.compile(
    r"^(?P<form>[\w /-]+?)\s+-\s+(?P<company>.+?)\s+\((?P<cik>\d{10})\)\s+\((?P<role>[^)]+)\)"
)
_ITEM_RE = re.compile(r"Item\s+(\d\.\d{2})")
_ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")

# 8-K item number -> event taxonomy (see pipeline.enrich.EVENT_TYPES)
ITEM_EVENTS = {
    "1.01": "deal",
    "1.03": "bankruptcy",
    "2.01": "m&a",
    "2.02": "earnings",
    "2.05": "restructuring",
    "2.06": "impairment",
    "3.01": "listing",
    "3.02": "offering",
    "4.01": "accounting",
    "4.02": "accounting",
    "5.02": "management",
    "7.01": "disclosure",
    "8.01": "other",
}
FORM_EVENTS = {"424B4": "offering", "424B5": "offering", "S-1": "offering", "S-3": "offering", "SCHEDULE 13D": "activist", "SC 13D": "activist"}


def parse_items(summary: str | None) -> list[str]:
    return _ITEM_RE.findall(summary or "")


def event_from_items(items: list[str]) -> str | None:
    for item in items:  # first mapped item wins; earlier items are usually more material
        if item in ITEM_EVENTS and ITEM_EVENTS[item] != "other":
            return ITEM_EVENTS[item]
    return "other" if items else None


def parse_entry(entry, universe: TickerUniverse) -> RawArticle | None:
    m = _TITLE_RE.match(entry.get("title", ""))
    if not m or m["form"].endswith("/A"):  # amendments are mostly noise
        return None
    form = m["form"]
    # 13D filings appear once per party; the "Subject" row is the company the stake is in
    if form == "SCHEDULE 13D" and m["role"] != "Subject":
        return None
    if form != "SCHEDULE 13D" and m["role"] != "Filer":
        return None
    cik = int(m["cik"])
    items = parse_items(entry.get("summary")) if form == "8-K" else []
    company = m["company"].strip()
    title = f"{form}: {company}" + (f" (items {', '.join(items)})" if items else "")
    return RawArticle(
        url=entry.get("link"),
        title=title,
        published_at=entry_published(entry),
        source="edgar",
        source_name="SEC EDGAR",
        snippet=clean_html(entry.get("summary")),
        tickers={(t, "edgar") for t in universe.tickers_for_cik(cik)},
        event_type=event_from_items(items) if form == "8-K" else FORM_EVENTS.get(form),
        cik=cik,
        form=form,
        signals=[s.code for s in signals_for_filing(form, items)],
    )


class EdgarSource:
    name = "SEC EDGAR"

    def __init__(self, user_agent: str, universe: TickerUniverse, forms: list[str] = EVENT_FORMS):
        self.user_agent = user_agent
        self.universe = universe
        self.forms = forms

    def fetch(self) -> list[RawArticle]:
        seen: set[str] = set()
        articles = []
        errors: list[str] = []
        for i, form in enumerate(self.forms):
            if i:
                time.sleep(0.2)  # SEC fair access: stay well under 10 req/s
            try:
                resp = httpx.get(
                    FEED_URL,
                    params={"action": "getcurrent", "type": form, "owner": "include", "count": 100, "output": "atom"},
                    headers={"User-Agent": self.user_agent},
                    timeout=20,
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:  # one bad form shouldn't discard the others
                log.warning("EDGAR %s feed failed: %s", form, exc)
                errors.append(f"{form}: {exc}")
                continue
            for entry in feedparser.parse(resp.content).entries:
                raw = parse_entry(entry, self.universe)
                if raw is None or raw.form != form:
                    continue
                acc = _ACCESSION_RE.search(raw.url or "")
                key = acc.group(1) if acc else raw.url
                if key in seen:
                    continue
                seen.add(key)
                articles.append(raw)
        if errors and len(errors) == len(self.forms):
            raise RuntimeError(f"All EDGAR feeds failed: {'; '.join(errors)}")
        return articles


# --- Filing text ---------------------------------------------------------------

_SKIP_DOCS = re.compile(r"^(R\d+\.htm|FilingSummary|.*index|.*\.(xml|xsd|jpg|gif|png|css|js|json|zip|txt)$)", re.I)


def pick_document(names: list[str]) -> str | None:
    """Prefer the press release exhibit (EX-99.1), else the main document."""
    docs = [n for n in names if n.lower().endswith((".htm", ".html")) and not _SKIP_DOCS.match(n)]
    for n in docs:
        if re.search(r"ex[-_]?99", n, re.I):
            return n
    if docs:
        return docs[0]
    # Structured filings (e.g. Schedule 13D since 2025) ship only XML
    return "primary_doc.xml" if "primary_doc.xml" in names else None


def fetch_filing_text(index_url: str, user_agent: str, limit: int = 15000) -> str | None:
    """Readable text of a filing's key document, from its -index.htm URL."""
    folder = index_url.rsplit("/", 1)[0]
    headers = {"User-Agent": user_agent}
    resp = httpx.get(f"{folder}/index.json", headers=headers, timeout=20)
    resp.raise_for_status()
    names = [i["name"] for i in resp.json().get("directory", {}).get("item", [])]
    doc = pick_document(names)
    if not doc:
        return None
    resp = httpx.get(f"{folder}/{doc}", headers=headers, timeout=30)
    resp.raise_for_status()
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", resp.text)
    return clean_html(html, limit)
