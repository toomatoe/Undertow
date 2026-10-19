"""Live Form 4 forward test of the one pre-registered insider finding that was significant in-sample:
`insider_cluster_purchase`, micro bucket, 5 trading days (docs/results/event_study_insider_purchases_2026-10-19.json).

poll_form4(settings, universe, session_factory) runs inside the fast EDGAR poller (pipeline.ingest.poll_edgar,
its own try/except there) and:

1. fetches EDGAR "getcurrent" for type 4 (Atom, owner=include, count=100) with settings.sec_user_agent;
2. keeps the issuer-side entries ("4 - Company (CIK) (Issuer)") of issuers whose Company.size_bucket is
   'micro' (latest SEC public float from pipeline.companies, NOT the study's frozen CY2023Q2 frame: a live
   test can only use today's float; documented deviation);
3. for at most MAX_XML_PER_CYCLE new accessions (seen-set in {data_dir}/insider_live_seen.json) fetches the
   filing's index.json and the raw XML via form4.raw_xml_url, parses it with form4.parse_ownership_xml and
   applies the study's own qualification (study.exclusion_reason / study.insider_cik on TransactionRows built
   by rows_from_xml, a thin adapter): Form 4, code P / acquired, shares and price > 0, director or officer,
   not 10b5-1. The insider is the lowest director/officer CIK;
4. appends qualifying purchases (one line per filing) to {data_dir}/insider_live_purchases.jsonl;
5. evaluates each recent issuer-day with study.build_events (the same MIN_VALUE $10,000 issuer-day total and
   CLUSTER_DAYS window [d-10, d], purchases of any size counting toward the cluster) and, once per issuer-day,
   stores an Article (source 'edgar', form '4', signals ['insider_cluster_purchase']) through
   pipeline.ingest.store_and_publish, which broadcasts it and fires NEW_ARTICLE_HOOKS like any other filing.

Every SEC request goes through datasets.throttle() (<= 8/s). Gated on settings.edgar_enabled and
INSIDER_LIVE_ENABLED (insiders.settings, default true). Warm-up: the purchase store starts empty, so a cluster
whose first buyer filed before the first start is missed; clusters are fully observable about CLUSTER_DAYS
(10 calendar days) after the first start. No DB schema change; no orders.
"""

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import feedparser
import httpx
from sqlalchemy import select

from app.insiders import datasets, study
from app.insiders.datasets import Owner, TransactionRow
from app.insiders.form4 import UnsafeXMLError, parse_ownership_xml, raw_xml_url
from app.insiders.settings import get_live_settings
from app.models import Company
from app.pipeline.signals import FORWARD_TEST_SIGNALS
from app.research.eventstudy import ET
from app.sources.base import RawArticle
from app.sources.edgar import _ACCESSION_RE, _TITLE_RE
from app.sources.rss import entry_published

log = logging.getLogger("insiders.live")

SIGNAL = study.CLUSTER
assert SIGNAL in FORWARD_TEST_SIGNALS, "live signal must be registered in pipeline.signals.FORWARD_TEST_SIGNALS"
SIZE_BUCKET = "micro"  # the only bucket whose cluster result was significant under the pre-registered rule
EVIDENCE_HORIZON = 5  # trading days

FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
FEED_PARAMS = {"action": "getcurrent", "type": "4", "owner": "include", "count": 100, "output": "atom"}
INDEX_JSON_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{accession}-index.htm"
MAX_XML_PER_CYCLE = 25  # filings whose XML is fetched per poll (2 SEC requests each)
MAX_XML_BYTES = 2_000_000
SEEN_FILE = "insider_live_seen.json"
PURCHASES_FILE = "insider_live_purchases.jsonl"
SEEN_MAX = 20_000  # accessions kept in the seen-set (oldest dropped)
REEVALUATE_DAYS = 3  # issuer-days this recent are re-checked each cycle (covers a crash between store and emit)
TIMEOUT = 20

_FILED_RE = re.compile(r"Filed:\s*(?:</b>)?\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)

HttpGet = Callable[..., httpx.Response]


@dataclass(frozen=True)
class FeedEntry:
    accession: str
    issuer_cik: int
    company: str
    filing_date: date
    accepted_at: datetime  # tz-aware UTC


# --- Feed ------------------------------------------------------------------------


def parse_feed(content: bytes) -> list[FeedEntry]:
    """Issuer-side Form 4 entries of a getcurrent Atom feed (amendments and reporting-owner rows dropped),
    deduped by accession, oldest first."""
    out: dict[str, FeedEntry] = {}
    for entry in feedparser.parse(content).entries:
        m = _TITLE_RE.match(entry.get("title", ""))
        if not m or m["form"].strip() != "4" or m["role"] != "Issuer":
            continue
        acc = _ACCESSION_RE.search(entry.get("link") or "") or _ACCESSION_RE.search(entry.get("id") or "")
        if not acc:
            continue
        accepted = entry_published(entry)
        filed = _FILED_RE.search(entry.get("summary") or "")
        try:
            filing_date = date.fromisoformat(filed.group(1)) if filed else accepted.astimezone(ET).date()
        except ValueError:
            filing_date = accepted.astimezone(ET).date()
        out.setdefault(acc.group(1), FeedEntry(acc.group(1), int(m["cik"]), m["company"].strip(), filing_date, accepted))
    return sorted(out.values(), key=lambda e: (e.accepted_at, e.accession))


# --- Shared qualification (adapter to the study's TransactionRow rules) ----------


def rows_from_xml(parsed: dict, accession: str, filing_date: date) -> list[TransactionRow]:
    """One TransactionRow per nonDerivativeTransaction of a parsed Form 4, so study.exclusion_reason and
    study.insider_cik apply unchanged. Owners without a CIK are dropped; owners sorted by CIK (as datasets)."""
    owners = tuple(sorted(
        (Owner(o["cik"], o.get("name") or "", bool(o.get("is_director")), bool(o.get("is_officer")),
               bool(o.get("is_ten_percent")), o.get("officer_title") or "")
         for o in parsed.get("reporting_owners", []) if o.get("cik") is not None),
        key=lambda o: o.cik,
    ))
    issuer = parsed.get("issuer") or {}
    rows = []
    for tx in parsed.get("transactions", []):
        rows.append(TransactionRow(
            accession=accession,
            filing_date=filing_date,
            document_type=(parsed.get("document_type") or "").strip(),
            issuer_cik=issuer.get("cik"),
            issuer_ticker=issuer.get("ticker") or "",
            aff10b5one=parsed.get("aff10b5one"),
            owners=owners,
            security_title=tx.get("security_title") or "",
            trans_date=date.fromisoformat(tx["date"]) if tx.get("date") else None,
            code=(tx.get("code") or "").strip().upper(),
            acquired_disposed=(tx.get("acquired_disposed") or "").strip().upper(),
            shares=tx.get("shares"),
            price=tx.get("price"),
            shares_after=tx.get("shares_after"),
            direct_indirect=tx.get("direct_indirect") or "",
        ))
    return rows


def qualifying_purchases(parsed: dict, accession: str, filing_date: date) -> list[study.Purchase]:
    """The study's qualifying purchases of one parsed filing (same filters, same insider identity rule)."""
    out = []
    for row in rows_from_xml(parsed, accession, filing_date):
        if not study.is_qualifying(row) or row.issuer_cik is None:
            continue
        out.append(study.Purchase(row.issuer_cik, study.insider_cik(row), filing_date, row.trans_date, row.value, accession))
    return out


# --- Persistence -----------------------------------------------------------------


def _seen_path(data_dir: str) -> str:
    return os.path.join(data_dir, SEEN_FILE)


def _purchases_path(data_dir: str) -> str:
    return os.path.join(data_dir, PURCHASES_FILE)


def load_state(data_dir: str) -> dict:
    """{"seen": [accession, ...], "emitted": ["<issuer_cik>:<YYYY-MM-DD>", ...]}; empty when missing/corrupt."""
    try:
        with open(_seen_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {"seen": [str(a) for a in data.get("seen", [])], "emitted": [str(k) for k in data.get("emitted", [])]}
    except (OSError, ValueError):
        pass
    return {"seen": [], "emitted": []}


def save_state(data_dir: str, state: dict) -> None:
    os.makedirs(data_dir, exist_ok=True)
    payload = {"seen": state["seen"][-SEEN_MAX:], "emitted": state["emitted"][-SEEN_MAX:]}
    tmp = _seen_path(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, _seen_path(data_dir))


def append_purchase(data_dir: str, record: dict) -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(_purchases_path(data_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def load_purchases(data_dir: str) -> list[dict]:
    """Stored qualifying purchases (one dict per filing). Malformed lines are skipped."""
    out = []
    try:
        with open(_purchases_path(data_dir), encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    rec["filing_date"] = date.fromisoformat(rec["filing_date"])
                    out.append(rec)
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return out


def _as_purchase(rec: dict) -> study.Purchase:
    return study.Purchase(int(rec["issuer_cik"]), int(rec["insider_cik"]), rec["filing_date"], None,
                          float(rec["value"]), str(rec["accession"]))


# --- Cluster evaluation (study.build_events) --------------------------------------


@dataclass(frozen=True)
class ClusterEvent:
    issuer_cik: int
    filing_date: date
    insiders: int  # distinct insiders with qualifying purchases in [d - CLUSTER_DAYS, d]
    total_value: float  # qualifying purchases filed on d
    accessions: tuple[str, ...]  # filings of d


def evaluate(records: list[dict], issuer_cik: int, day: date) -> ClusterEvent | None:
    """The study's issuer-day event logic: a cluster event when build_events emits CLUSTER for (issuer, day)."""
    purchases = [_as_purchase(r) for r in records if int(r["issuer_cik"]) == issuer_cik]
    events = study.build_events(study.InsiderData(purchases=purchases), window=(day, day))
    if not any(sig == study.CLUSTER and d == day for sig, d, _ in events.get(issuer_cik, [])):
        return None
    lo = day - timedelta(days=study.CLUSTER_DAYS)
    group = [p for p in purchases if p.filing_date == day]
    return ClusterEvent(
        issuer_cik=issuer_cik,
        filing_date=day,
        insiders=len({p.insider_cik for p in purchases if lo <= p.filing_date <= day}),
        total_value=sum(p.value for p in group),
        accessions=tuple(sorted({p.accession for p in group})),
    )


def headline(ticker: str, ev: ClusterEvent) -> str:
    return f"Insider cluster purchase: {ticker} ({ev.insiders} insiders, ${ev.total_value:,.0f} total)"


def to_raw_article(ev: ClusterEvent, ticker: str, company: str, accepted_at: datetime) -> RawArticle:
    last = ev.accessions[-1]
    url = FILING_INDEX_URL.format(cik=ev.issuer_cik, acc=last.replace("-", ""), accession=last)
    snippet = (
        f"{ev.insiders} different directors or officers of {company} reported open-market purchases on Form 4 "
        f"(code P, not under a 10b5-1 plan) within {study.CLUSTER_DAYS} days; ${ev.total_value:,.0f} of qualifying "
        f"purchases filed on {ev.filing_date.isoformat()}. Forward test of a pre-registered in-sample finding; "
        "historical figures are hypothetical."
    )
    return RawArticle(
        url=url,
        title=headline(ticker, ev),
        published_at=accepted_at,
        source="edgar",
        source_name="SEC EDGAR",
        snippet=snippet,
        tickers={(ticker, "edgar")},
        cik=ev.issuer_cik,
        form="4",
        signals=[SIGNAL],
    )


# --- SEC fetches -----------------------------------------------------------------


def fetch_form4_xml(entry: FeedEntry, user_agent: str, http_get: HttpGet) -> bytes | None:
    """Raw Form 4 XML via the filing's index.json and form4.raw_xml_url. None when the filing has no XML
    (permanent); raises httpx.HTTPError on transient failures (retried next cycle)."""
    acc = entry.accession.replace("-", "")
    datasets.throttle()
    resp = http_get(INDEX_JSON_URL.format(cik=entry.issuer_cik, acc=acc), headers={"User-Agent": user_agent}, timeout=TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    try:
        items = resp.json().get("directory", {}).get("item", [])
    except ValueError:
        return None
    names = [str(i.get("name", "")) for i in items if isinstance(i, dict)]
    xmls = [n for n in names if n.lower().endswith(".xml") and "/" not in n]
    if not xmls:
        return None
    datasets.throttle()
    resp = http_get(raw_xml_url(entry.issuer_cik, entry.accession, xmls[0]), headers={"User-Agent": user_agent}, timeout=TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    if len(resp.content) > MAX_XML_BYTES:
        return None
    return resp.content


def _micro_issuers(session_factory, ciks: set[int]) -> dict[int, tuple[str, str]]:
    """issuer CIK -> (ticker, name) for Companies in the micro bucket (lowest symbol when a CIK has several)."""
    if not ciks:
        return {}
    with session_factory() as session:
        rows = session.execute(
            select(Company.cik, Company.symbol, Company.name)
            .where(Company.cik.in_(ciks), Company.size_bucket == SIZE_BUCKET)
            .order_by(Company.symbol)
        ).all()
    out: dict[int, tuple[str, str]] = {}
    for cik, symbol, name in rows:
        out.setdefault(int(cik), (symbol, name))
    return out


def poll_form4(settings, universe, session_factory, *, http_get: HttpGet = httpx.get, now: datetime | None = None) -> dict:
    """One forward-test cycle. Returns counters; never touches the 8-K path."""
    if not settings.edgar_enabled or not get_live_settings().insider_live_enabled:
        return {"status": "disabled"}
    from app.pipeline.ingest import store_and_publish  # late import: ingest imports this module lazily too

    now = now or datetime.now(timezone.utc)
    ua = settings.sec_user_agent
    data_dir = settings.data_dir
    stats = {"entries": 0, "already_seen": 0, "not_micro": 0, "capped": 0, "xml_fetched": 0, "fetch_errors": 0,
             "no_xml": 0, "unsafe_xml": 0, "parse_errors": 0, "not_qualifying": 0, "qualifying_filings": 0, "emitted": 0}

    datasets.throttle()
    resp = http_get(FEED_URL, params=FEED_PARAMS, headers={"User-Agent": ua}, timeout=TIMEOUT)
    resp.raise_for_status()
    entries = parse_feed(resp.content)
    stats["entries"] = len(entries)

    state = load_state(data_dir)
    seen = set(state["seen"])
    micro = _micro_issuers(session_factory, {e.issuer_cik for e in entries})
    accepted: dict[str, datetime] = {}

    for entry in entries:
        if entry.accession in seen:
            stats["already_seen"] += 1
            continue
        if entry.issuer_cik not in micro:
            stats["not_micro"] += 1
            continue
        if stats["xml_fetched"] >= MAX_XML_PER_CYCLE:
            stats["capped"] += 1
            continue
        stats["xml_fetched"] += 1
        try:
            xml = fetch_form4_xml(entry, ua, http_get)
        except httpx.HTTPError as exc:
            stats["fetch_errors"] += 1
            log.info("Form 4 %s unavailable this cycle: %s", entry.accession, exc)
            continue
        seen.add(entry.accession)
        state["seen"].append(entry.accession)
        if xml is None:
            stats["no_xml"] += 1
            continue
        try:
            parsed = parse_ownership_xml(xml)
        except UnsafeXMLError:
            stats["unsafe_xml"] += 1
            log.warning("Form 4 %s rejected: DOCTYPE/ENTITY declaration", entry.accession)
            continue
        except ValueError as exc:
            stats["parse_errors"] += 1
            log.info("Form 4 %s unparseable: %s", entry.accession, exc)
            continue
        purchases = [p for p in qualifying_purchases(parsed, entry.accession, entry.filing_date)
                     if p.issuer_cik == entry.issuer_cik]
        if not purchases:
            stats["not_qualifying"] += 1
            continue
        stats["qualifying_filings"] += 1
        ticker, _ = micro[entry.issuer_cik]
        append_purchase(data_dir, {
            "accession": entry.accession,
            "issuer_cik": entry.issuer_cik,
            "ticker": ticker,
            "insider_cik": purchases[0].insider_cik,  # one insider per filing (lowest director/officer CIK)
            "filing_date": entry.filing_date.isoformat(),
            "value": round(sum(p.value for p in purchases), 2),
            "accepted_at": entry.accepted_at.isoformat(),
        })
        accepted[entry.accession] = entry.accepted_at
    save_state(data_dir, state)

    # Re-check every recent issuer-day not yet emitted (idempotent across cycles and restarts).
    records = load_purchases(data_dir)
    emitted = set(state["emitted"])
    recent = now.astimezone(ET).date() - timedelta(days=REEVALUATE_DAYS)
    days = sorted({(int(r["issuer_cik"]), r["filing_date"]) for r in records if r["filing_date"] >= recent},
                  key=lambda k: (k[1], k[0]))
    names = _micro_issuers(session_factory, {cik for cik, _ in days})
    raws, keys = [], []
    for cik, day in days:
        key = f"{cik}:{day.isoformat()}"
        if key in emitted:
            continue
        ev = evaluate(records, cik, day)
        if ev is None:
            continue
        recs = {r["accession"]: r for r in records if int(r["issuer_cik"]) == cik}
        ticker = names.get(cik, (recs[ev.accessions[-1]].get("ticker"), ""))[0]
        if not ticker:
            continue
        company = names.get(cik, (ticker, ticker))[1] or ticker
        last = recs[ev.accessions[-1]]
        when = accepted.get(ev.accessions[-1])
        if when is None:
            try:
                when = datetime.fromisoformat(last["accepted_at"])
            except (KeyError, TypeError, ValueError):
                when = now
        raws.append(to_raw_article(ev, ticker, company, when))
        keys.append(key)
    if raws:
        store_and_publish(raws, universe, body="")
        state["emitted"].extend(keys)
        save_state(data_dir, state)
        stats["emitted"] = len(raws)
        log.info("Insider cluster forward test: %d new issuer-day event(s)", len(raws))
    return stats
