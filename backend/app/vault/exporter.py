"""Export Undertow's data as plain Markdown into `<vault_dir>/Undertow/` (an Obsidian vault folder).

Never imports app.main: everything main-specific (evidence lookup, paper portfolio) is passed in as callables.
Never reads Settings: no setting other than the vault/data paths given as arguments reaches the vault.
Layout, policies and the public API are documented in app/vault/AGENTS.md.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fundamentals import service as fundamentals
from app.journal import digest
from app.journal import service as journal
from app.models import Article, Company, JournalEntry, WatchlistItem
from app.newsletter import service as newsletter
from app.pipeline.signals import FORWARD_TEST_SIGNALS
from app.vault import frontmatter as fm
from app.vault import render as r
from app.vault.frontmatter import iso_utc, wikilink
from app.vault.fs import VaultFS, sanitize
from app.vault.writer import CONFLICTS, Outcome, write_copy, write_fenced, write_machine, write_once

log = logging.getLogger(__name__)

# Callers hold this around export_vault so two runs (scheduler + manual trigger) never overlap. export_vault does
# not take it itself (a caller already holding it would deadlock on a plain Lock).
EXPORT_LOCK = threading.Lock()

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BASES_DIR = os.path.join(PACKAGE_DIR, "bases")
STATIC_DIR = os.path.join(PACKAGE_DIR, "static")
WORKING_PAPER = os.path.join(PACKAGE_DIR, "working_paper.md")
STATE_FILE = "vault_state.json"
DEFAULT_STUDY_FILES = {
    "main": "event_study.json",
    "oos": "event_study_oos.json",
    "insider_purchases": "event_study_insider_purchases.json",
}
STUDY_TITLES = {
    "main": "In-sample event study",
    "oos": "Pre-registered out-of-sample study",
    "insider_purchases": "Form 4 insider purchase study (pre-registered)",
}
FOLDERS = ("Tickers", "Signals", "Journal", "Briefs", "Studies", "Paper", "Newsletter", "Bases")
SOURCE = "undertow"
MY_NOTES = "\n## My notes\n\n"
OPEN_STATUSES = ("waiting", "open")
RESOLVED_STATUSES = ("complete", "data_ended", "no_data")
TICKER_FILINGS = 20
STUDY_SIGNIFICANT_ROWS = 25
STUDY_OTHER_ROWS = 5
INDEX_LINKS = 50
OUTCOME_LABEL = "Hypothetical: abnormal return vs IWM from the day 0 + 1 close; not traded, not investment advice"
PAPER_LABEL = "Hypothetical: simulated from the forward signal journal, not traded, not investment advice"
LOG_HEADER = (
    "# Undertow export log\n\n"
    "One line per export run that changed something or had conflicts or errors. Append-only.\n\n"
)

EvidenceFn = Callable[[str, str], object]
PaperFn = Callable[[], dict | None]


@dataclass
class ExportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts: int = 0
    errors: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    conflict_paths: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def add(self, folder: str, outcome: Outcome, vfs: VaultFS) -> None:
        self.counts[folder] = self.counts.get(folder, 0) + 1
        if outcome.status == "conflict":
            self.conflicts += 1
            if outcome.conflict_path:
                self.conflict_paths.append(vfs.rel(outcome.conflict_path))
        elif outcome.status in ("created", "updated", "unchanged"):
            setattr(self, outcome.status, getattr(self, outcome.status) + 1)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.conflicts or self.errors)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("started_at", "finished_at"):
            d[k] = iso_utc(d[k]) if d[k] else None
        return d


# --- helpers -----------------------------------------------------------------------------------------------------


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _primary_symbol(a: Article) -> str | None:
    tickers = sorted(a.tickers or [], key=lambda t: (t.method != "edgar", t.symbol))
    return tickers[0].symbol.upper() if tickers else None


def _signal_stem(a: Article) -> str:
    day = _aware(a.published_at).date().isoformat()
    acc = r.accession_from_url(a.url)
    suffix = acc.rsplit("-", 1)[-1] if acc else f"a{a.id}"
    return sanitize(f"{day}-{_primary_symbol(a) or 'NOTICKER'}-{a.form or 'filing'}-{suffix}")


def _codes(a: Article) -> list[str]:
    return [c for c in (a.signals or []) if isinstance(c, str)]


def _chain_days(data_dir: str) -> dict[str, str]:
    """{day: hash} of sealed days in {data_dir}/journal_chain.jsonl (tolerant: stops at the first bad line)."""
    out: dict[str, str] = {}
    try:
        with open(digest.chain_path(data_dir), encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    out[str(rec["day"])] = str(rec["hash"])
                except (ValueError, KeyError, TypeError):
                    break
    except OSError:
        pass
    return out


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def make_evidence_fn(data_dir: str, horizon: int = 20) -> EvidenceFn:
    """Convenience evidence lookup without app.main: main-study rows at `horizon` from {data_dir}/event_study.json;
    forward-test signals from the insider study's row (app.insiders.evidence), never from event_study.json."""
    from app.insiders import evidence as insider_evidence
    from app.pipeline.signals import is_forward_test

    study = _read_json(os.path.join(data_dir, DEFAULT_STUDY_FILES["main"])) or {}
    main_rows = {
        (row.get("signal"), row.get("bucket")): row
        for row in study.get("results") or [] if isinstance(row, dict) and row.get("horizon_days") == horizon
    }
    try:
        fwd, _origin = insider_evidence.load_forward_test_row(data_dir)
    except Exception:  # never let a broken study file stop the export
        fwd = None

    def lookup(code: str, bucket: str):
        if is_forward_test(code):
            if fwd and fwd.get("signal") == code and fwd.get("bucket") == bucket:
                return fwd
            return None
        return main_rows.get((code, bucket))

    return lookup


class _Ctx:
    def __init__(self, session, vfs, data_dir, lookback_days, evidence_fn, paper_fn, now):
        self.session: Session = session
        self.vfs: VaultFS = vfs
        self.data_dir: str = data_dir
        self.now: datetime = now
        self.today: date = now.date()
        self.since: datetime = now - timedelta(days=lookback_days)
        self.lookback_days = lookback_days
        self.evidence_fn = evidence_fn
        self.paper_fn = paper_fn
        self.ts = now.strftime("%Y%m%dT%H%M%SZ")
        self.generated_at = now.replace(microsecond=0)  # emitted unquoted as an ISO UTC timestamp
        self.companies: dict[str, Company] = {}
        self.articles: list[Article] = []
        self.journal_by_article: dict[int, JournalEntry] = {}
        self.entries: list[JournalEntry] = []
        self.chain: dict[str, str] = {}
        self.signal_stems: dict[int, str] = {}
        self._paper: dict | None = None
        self._paper_loaded = False

    def evidence(self, code: str, bucket: str | None) -> dict | None:
        if self.evidence_fn is None or not bucket:
            return None
        try:
            return r.normalize_evidence(self.evidence_fn(code, bucket), bucket)
        except Exception:
            log.exception("Vault: evidence lookup failed for %s/%s", code, bucket)
            return None

    def paper(self) -> dict | None:
        if not self._paper_loaded:
            self._paper_loaded = True
            if self.paper_fn is not None:
                try:
                    self._paper = self.paper_fn()
                except Exception:
                    log.exception("Vault: paper portfolio callable failed")
        return self._paper

    def bucket(self, symbol: str | None) -> str | None:
        c = self.companies.get(symbol or "")
        return c.size_bucket if c else None


def _guard(result: ExportResult, what: str, fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        result.errors += 1
        log.exception("Vault: %s failed", what)


# --- Signals -----------------------------------------------------------------------------------------------------


def _signal_note(ctx: _Ctx, a: Article) -> tuple[str, str]:
    stem = _signal_stem(a)
    sym = _primary_symbol(a)
    codes = _codes(a)
    primary = codes[0] if codes else None
    bucket = ctx.bucket(sym)
    ev = ctx.evidence(primary, bucket) if primary else None
    evf = ev or {k: None for k in r.EVIDENCE_KEYS}
    if not ev:
        evf["bucket"] = bucket
    acc = r.accession_from_url(a.url)
    je = ctx.journal_by_article.get(a.id)
    forward = any(c in FORWARD_TEST_SIGNALS for c in codes)
    filed = _aware(a.published_at)
    fields: list[tuple[str, object]] = [
        ("type", "signal"),
        ("source", SOURCE),
        ("generated_at", ctx.generated_at),
        ("ticker", wikilink(sym) if sym else None),
        ("form", a.form),
        ("items", r.items_from_title(a.title)),
        ("accession", acc),
        ("filed_at", filed),
        ("edgar_url", a.url),
        ("signals", codes),
        ("signal_names", [r.signal_label(c) for c in codes]),
        ("direction", r.signal_direction(primary) if primary else None),
        ("severity", a.severity),
        ("size_bucket", bucket),
        *[(k, evf.get(k)) for k in r.EVIDENCE_KEYS],
        ("forward_test", forward),
    ]
    if je is not None:
        fields.append(("journal_id", je.id))
    fields.append(("tags", ["undertow/signal"]))

    labels = "; ".join(r.signal_label(c) for c in codes) or "filing"
    excerpt = r.clean_third_party(a.ai_summary or a.snippet)
    lines = [
        f"# {sym or 'Unknown ticker'} {a.form or 'filing'}: {labels}",
        "",
        f"Filed {filed.strftime('%Y-%m-%d %H:%M')} UTC. Source: [SEC EDGAR filing]({a.url})"
        + (f" (accession {acc})" if acc else "") + ".",
        "",
    ]
    if excerpt:
        lines += [f"> {excerpt}", "", "Excerpt only; read the filing on EDGAR for the full text.", ""]
    lines += ["## Evidence", "", r.evidence_sentence(primary, ev) if primary else "No signal code recorded.", ""]
    lines += ["## Caveats", "",
              "- Machine-generated from the SEC filing index. Read the filing itself before drawing any conclusion.",
              "- Event-study numbers are historical averages over many past filings: not a forecast for this company "
              "and not investment advice.",
              "- Size bucket from the company's last reported public float (it can be stale)."]
    if forward:
        lines.append("- Forward test of a pre-registered finding: the evidence shown is the in-sample result of the "
                     "separate insider study, now being tested live.")
    if je is not None:
        lines.append(f"- Journal entry: [[Undertow/Journal/{je.id}|Journal {je.id}]].")
    body = "\n" + "\n".join(lines) + "\n"
    return stem, fm.emit(fields) + body


def _export_signals(ctx: _Ctx, result: ExportResult) -> None:
    for a in ctx.articles:
        try:
            stem, text = _signal_note(ctx, a)
            ctx.signal_stems[a.id] = stem
            result.add("Signals", write_once(ctx.vfs, ctx.vfs.path("Signals", f"{stem}.md"), text), ctx.vfs)
        except Exception:
            result.errors += 1
            log.exception("Vault: signal note for article %s failed", a.id)


# --- Tickers -----------------------------------------------------------------------------------------------------


def _dilution_lines(ctx: _Ctx, cik: int | None) -> list[str]:
    """Only from the already-cached companyfacts file; never a network call."""
    if not cik:
        return ["No CIK on file for this ticker."]
    facts = _read_json(os.path.join(ctx.data_dir, "companyfacts", f"{int(cik)}.json"))
    if not isinstance(facts, dict):
        return ["No cached SEC XBRL data for this company yet (opening its ticker page in Undertow fetches it)."]
    cash = fundamentals.latest_cash(facts)
    ocf = fundamentals.ttm_operating_cash_flow(facts)
    rw = fundamentals.runway(cash, ocf)
    _hist, change = fundamentals.share_history(facts)
    out = ["Arithmetic on reported SEC XBRL numbers (cached copy), not a forecast."]
    out.append(f"- Cash and short-term investments: {r.money(cash['value'])} as of {cash['as_of']}" if cash
               else "- Cash: not reported in XBRL")
    if ocf:
        out.append(f"- Operating cash flow ({ocf['method']}, period ending {ocf['period_end']}): {r.money(ocf['value'])}")
    if rw.get("status") == "burning" and rw.get("months") is not None:
        out.append(f"- Runway: about {rw['months']} months at the reported burn of {r.money(rw.get('monthly_burn'))} "
                   f"per month (as of the cash date, before any later raise)")
    elif rw.get("status") == "cash_flow_positive":
        out.append("- Runway: operating cash flow was positive over the period")
    else:
        out.append("- Runway: unknown (missing cash or cash-flow tags)")
    if change:
        out.append(f"- Shares outstanding: {r.pct(change['change'])} over {change['days']} days "
                   f"({change['from']} to {change['to']})")
    return out


def _export_tickers(ctx: _Ctx, result: ExportResult) -> None:
    by_symbol: dict[str, list[Article]] = {}
    for a in ctx.articles:
        for t in a.tickers or []:
            by_symbol.setdefault(t.symbol.upper(), []).append(a)
    watch = [w.upper() for w in ctx.session.scalars(select(WatchlistItem.symbol)).all()]
    symbols = sorted(set(by_symbol) | set(watch))
    open_counts: dict[str, int] = {}
    for e in ctx.entries:
        if e.status in OPEN_STATUSES:
            open_counts[e.ticker.upper()] = open_counts.get(e.ticker.upper(), 0) + 1
    for sym in symbols:
        try:
            _ticker_note(ctx, result, sym, by_symbol.get(sym, []), open_counts.get(sym, 0), sym in watch)
        except Exception:
            result.errors += 1
            log.exception("Vault: ticker note %s failed", sym)


def _ticker_note(ctx: _Ctx, result: ExportResult, sym: str, arts: list[Article], journal_open: int, watched: bool) -> None:
    c = ctx.companies.get(sym)
    arts = sorted(arts, key=lambda a: (_aware(a.published_at), a.id), reverse=True)
    active: list[str] = []
    for a in sorted(arts, key=lambda a: -(a.severity or 0)):
        for code in _codes(a):
            if code not in active:
                active.append(code)
    last = _aware(arts[0].published_at).date() if arts else None
    bucket = c.size_bucket if c else None
    fields: list[tuple[str, object]] = [
        ("type", "ticker"),
        ("source", SOURCE),
        ("generated_at", ctx.generated_at),
        ("ticker", sym),
        ("cik", c.cik if c else None),
        ("company", c.name if c else None),
        ("size_bucket", bucket),
        ("public_float_usd", c.public_float if c else None),
        ("last_filing", last),
        ("active_signals", active),
        ("journal_open", journal_open),
        ("watchlist", watched),
        ("tags", ["undertow/ticker"]),
        ("updated", ctx.generated_at),
    ]
    lines = [f"# {sym}" + (f": {c.name}" if c else ""), "",
             f"## Recent signal filings (last {ctx.lookback_days} days)", ""]
    if arts:
        lines += ["| Filed (UTC) | Form | Signals | Note |", "|---|---|---|---|"]
        for a in arts[:TICKER_FILINGS]:
            stem = ctx.signal_stems.get(a.id) or _signal_stem(a)
            lines.append(f"| {_aware(a.published_at).date().isoformat()} | {r.cell(a.form)} | "
                         f"{r.cell('; '.join(r.signal_label(x) for x in _codes(a)))} | [[{stem}]] |")
        if len(arts) > TICKER_FILINGS:
            lines.append(f"\n{len(arts) - TICKER_FILINGS} older filing(s) in the window not shown.")
    else:
        lines.append(f"No signal filings in the last {ctx.lookback_days} days.")
    dilution = _dilution_lines(ctx, c.cik if c else None)
    if not dilution[0].startswith("No "):  # skip the section when there is no cached XBRL data (most tickers)
        lines += ["", "## Dilution and cash runway", "", *dilution]
    lines += ["", "## Edge Lab evidence", ""]
    if active:
        lines += [f"- {r.evidence_sentence(code, ctx.evidence(code, bucket))}" for code in active]
    else:
        lines.append("No active signals.")
    block = "\n".join(lines)
    path = ctx.vfs.path("Tickers", f"{sym}.md")
    out = write_fenced(ctx.vfs, path, fields=fields, block=block, tail=MY_NOTES, conflict_name=sym, ts=ctx.ts)
    result.add("Tickers", out, ctx.vfs)


# --- Journal -----------------------------------------------------------------------------------------------------


def _journal_note(ctx: _Ctx, result: ExportResult, e: JournalEntry) -> None:
    c = digest.canonical_entry(e)
    day = journal.recorded_day(e).isoformat()
    horizon = journal.evaluation_horizon(e.primary_signal)
    ev = ctx.evidence(e.primary_signal, e.size_bucket)
    expected = ev["mean_abnormal"] if ev and ev.get("horizon_days") == horizon else None
    sealed_hash = ctx.chain.get(day)
    fields: list[tuple[str, object]] = [
        ("type", "journal"),
        ("source", SOURCE),
        ("generated_at", ctx.generated_at),
        ("entry_id", c["id"]),
        ("day", date.fromisoformat(day)),
        ("ticker", wikilink(c["ticker"].upper())),
        ("signal", c["primary_signal"]),
        ("signal_name", r.signal_label(c["primary_signal"])),
        ("signals", c["signals"] or []),
        ("direction", c["direction"]),
        ("horizon_days", horizon),
        ("expected", expected),
        ("expected_basis", f"{r.EVIDENCE_LABEL}: mean abnormal return at the evaluation horizon"),
        ("forward_test", journal.forward_test_label(e.primary_signal) is not None),
        ("article_id", c["article_id"]),
        ("cik", c["cik"]),
        ("form", c["form"]),
        ("severity", c["severity"]),
        ("size_bucket", c["size_bucket"]),
        ("public_float", c["public_float"]),
        ("filed_at", c["filed_at"]),
        ("created_at", c["created_at"]),
        ("borrow_fee", c["borrow_fee"]),
        ("borrow_available", c["borrow_available"]),
        ("borrow_snapshot", c["borrow_snapshot"]),
        ("sealed_day", date.fromisoformat(day) if sealed_hash else None),
        ("seal_hash", sealed_hash),
        ("tags", ["undertow/journal"]),
        ("outcome_status", e.status),
        ("outcome_resolved", e.status in RESOLVED_STATUSES),
        ("outcome_entry_date", e.entry_date),
        ("outcome_abn_1", e.abn_1),
        ("outcome_abn_5", e.abn_5),
        ("outcome_abn_20", e.abn_20),
        ("outcome_label", OUTCOME_LABEL),
    ]
    stem = ctx.signal_stems.get(e.article_id)
    label = r.signal_label(e.primary_signal)
    head_lines = [
        "", f"# Journal entry {e.id}: {c['ticker']} {label}", "",
        f"Recorded {c['created_at']} (UTC day {day}). Filed {c['filed_at']}.",
    ]
    if stem:
        head_lines.append(f"Signal note: [[{stem}]].")
    head_lines += [
        "",
        "The frontmatter fields above the `outcome_` keys are the sealed record (journal hash chain): never edit "
        "them. `sealed_day` and `seal_hash` are filled in once, when the day is sealed.",
        "",
    ]
    lines = ["## Outcome (hypothetical)", "",
             f"Status: {e.status}. Judged at {horizon} trading days"
             + (f"; entry priced on {e.entry_date.isoformat()}." if e.entry_date else "."), "",
             "| Horizon | Abnormal return vs IWM |", "|---|---|"]
    for h, v in ((1, e.abn_1), (5, e.abn_5), (20, e.abn_20)):
        lines.append(f"| {h} trading day{'s' if h > 1 else ''} | {r.pct(v)} |")
    if expected is not None:
        lines += ["", f"{r.EVIDENCE_LABEL} for comparison: {r.pct(expected)} at {horizon} trading days."]
    lines += ["", OUTCOME_LABEL + "."]
    path = ctx.vfs.path("Journal", f"{e.id}.md")
    out = write_fenced(
        ctx.vfs, path, fields=fields, block="\n".join(lines), head="\n".join(head_lines) + "\n", tail=MY_NOTES,
        hash_key="outcome_hash", conflict_name=f"journal-{e.id}", ts=ctx.ts, sealed=True,
        fill_once=("sealed_day", "seal_hash"),
    )
    result.add("Journal", out, ctx.vfs)


def _export_journal(ctx: _Ctx, result: ExportResult) -> None:
    for e in ctx.entries:
        try:
            _journal_note(ctx, result, e)
        except Exception:
            result.errors += 1
            log.exception("Vault: journal note %s failed", e.id)


# --- Briefs ------------------------------------------------------------------------------------------------------


def _paper_on(paper: dict | None, day: date) -> tuple[float | None, float | None, float | None]:
    """(value, return since start, change vs previous point) of the hypothetical portfolio on or before `day`."""
    if not isinstance(paper, dict):
        return None, None, None
    curve = [p for p in paper.get("equity_curve") or [] if isinstance(p, dict) and p.get("date") and p.get("equity") is not None]
    curve = [p for p in curve if str(p["date"])[:10] <= day.isoformat()]
    if not curve:
        return None, None, None
    value = float(curve[-1]["equity"])
    start = (paper.get("assumptions") or {}).get("starting_capital")
    ret = value / float(start) - 1 if start else None
    chg = value - float(curve[-2]["equity"]) if len(curve) > 1 else None
    return round(value, 2), (round(ret, 6) if ret is not None else None), (round(chg, 2) if chg is not None else None)


def _brief_lines(ctx: _Ctx, day: date, arts: list[Article], blank: bool) -> list[str]:
    """Brief prose. blank=True replaces third-party names (tickers, note names) with X for the banned-word check."""
    def name(s: str | None) -> str:
        return "X" if blank else (s or "n/a")

    syms = sorted({s for a in arts if (s := _primary_symbol(a))})
    lines = [f"# Undertow brief {day.isoformat()}", "",
             f"{len(arts)} signal filing(s) recorded on {day.isoformat()} (UTC) across {len(syms)} ticker(s).", "",
             "## Signal filings", ""]
    if arts:
        for a in arts:
            stem = ctx.signal_stems.get(a.id) or _signal_stem(a)
            labels = "; ".join(r.signal_label(c) for c in _codes(a)) or "filing"
            lines.append(f"- [[{name(stem)}]] {name(_primary_symbol(a))} {a.form or 'filing'}: {labels} "
                         f"(severity {a.severity})")
    else:
        lines.append("None recorded.")
    lines += ["", "## Journal entries sealed this day", ""]
    recorded = [e for e in ctx.entries if journal.recorded_day(e) == day]
    if day.isoformat() not in ctx.chain:
        lines.append("This day is not sealed yet" + ("; entries recorded so far:" if recorded else "."))
    elif not recorded:
        lines.append("Sealed with no entries.")
    for e in recorded:
        lines.append(f"- [[Undertow/Journal/{e.id}|Journal {e.id}]] {name(e.ticker)} {r.signal_label(e.primary_signal)}")
    lines += ["", "## Paper portfolio (hypothetical)", ""]
    value, ret, chg = _paper_on(ctx.paper(), day)
    if value is None:
        lines.append("No hypothetical paper portfolio data for this day.")
    else:
        lines.append(f"Hypothetical paper portfolio value: {r.money(value)} ({r.pct(ret)} since the start"
                     + (f"; {'+' if chg >= 0 else '-'}{r.money(abs(chg))} vs the previous close" if chg is not None else "")
                     + "). " + PAPER_LABEL + ".")
    return lines


def _brief_note(ctx: _Ctx, result: ExportResult, day: date, arts: list[Article]) -> None:
    path = ctx.vfs.path("Briefs", f"{day.isoformat()}.md")
    if day != ctx.today and ctx.vfs.read_bytes(path) is not None:
        result.add("Briefs", Outcome("unchanged", path), ctx.vfs)  # past briefs are frozen
        return
    real, blanked = _brief_lines(ctx, day, arts, False), _brief_lines(ctx, day, arts, True)
    kept = []
    for line, check in zip(real, blanked):
        if bad := newsletter.banned_words(check):
            log.error("Vault: brief %s line dropped for banned words %s: %r", day, bad, check)
            continue
        kept.append(line)
    value, ret, _chg = _paper_on(ctx.paper(), day)
    fields: list[tuple[str, object]] = [
        ("type", "brief"),
        ("source", SOURCE),
        ("generated_at", ctx.generated_at),
        ("date", day),
        ("signals_count", len(arts)),
        ("tickers", sorted({s for a in arts if (s := _primary_symbol(a))})),
        ("forward_test_signals", sum(1 for a in arts if any(c in FORWARD_TEST_SIGNALS for c in _codes(a)))),
        ("paper_portfolio_value", value),
        ("paper_portfolio_return", ret),
        ("paper_label", PAPER_LABEL if value is not None else None),
        ("tags", ["undertow/brief"]),
    ]
    out = write_fenced(ctx.vfs, path, fields=fields, block="\n".join(kept), tail=MY_NOTES,
                       conflict_name=f"brief-{day.isoformat()}", ts=ctx.ts)
    result.add("Briefs", out, ctx.vfs)


def _export_briefs(ctx: _Ctx, result: ExportResult) -> None:
    by_day: dict[date, list[Article]] = {ctx.today: []}
    for a in ctx.articles:
        by_day.setdefault(_aware(a.published_at).date(), []).append(a)
    for day in sorted(by_day):
        try:
            _brief_note(ctx, result, day, by_day[day])
        except Exception:
            result.errors += 1
            log.exception("Vault: brief %s failed", day)


# --- Studies, paper, newsletter, static files --------------------------------------------------------------------


def _study_table(rows: list[dict]) -> list[str]:
    out = ["| Signal | Size | Horizon (days) | n | Mean abnormal | Excess vs baseline | t | Significant |",
           "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        out.append(
            f"| {r.cell(r.signal_label(str(row.get('signal'))))} | {r.cell(row.get('bucket'))} | {r.cell(row.get('horizon_days'))} "
            f"| {r.cell(row.get('n'))} | {r.pct(row.get('mean_abnormal'))} | {r.pct(row.get('excess_vs_baseline'))} "
            f"| {r.cell(row.get('t_stat'))} | {'yes' if row.get('significant') else 'no'} |"
        )
    return out


def _study_note(ctx: _Ctx, result: ExportResult, name: str, filename: str) -> None:
    path_in = os.path.join(ctx.data_dir, filename)
    if not os.path.exists(path_in):
        return
    doc = _read_json(path_in)
    if not isinstance(doc, dict):
        raise ValueError(f"{filename} is not a JSON object")
    rows = [x for x in doc.get("results") or [] if isinstance(x, dict)]

    def abs_t(x):
        try:
            return -abs(float(x.get("t_stat") or 0))
        except (TypeError, ValueError):
            return 0

    sig = sorted([x for x in rows if x.get("significant")], key=abs_t)
    rest = sorted([x for x in rows if not x.get("significant")], key=abs_t)
    title = STUDY_TITLES.get(name, name)
    fields: list[tuple[str, object]] = [
        ("type", "study"),
        ("source", SOURCE),
        ("generated_at", ctx.generated_at),
        ("study", name),
        ("study_file", os.path.basename(filename)),
        ("study_generated_at", str(doc.get("generated_at")) if doc.get("generated_at") else None),
        ("n_results", len(rows)),
        ("n_significant", len(sig)),
        ("tags", ["undertow/study"]),
    ]
    lines = ["", f"# Study: {title}", "",
             "Historical event-study results (hypothetical, not a forecast): average market-adjusted moves after past "
             "filings. Not investment advice. Full write-up: [[working-paper]].", "",
             "## Significant after multiple-testing correction", ""]
    lines += _study_table(sig[:STUDY_SIGNIFICANT_ROWS]) if sig else ["None."]
    if len(sig) > STUDY_SIGNIFICANT_ROWS:
        lines.append(f"\n{len(sig) - STUDY_SIGNIFICANT_ROWS} more not shown.")
    lines += ["", "## Largest t-statistics among the rest", ""]
    lines += _study_table(rest[:STUDY_OTHER_ROWS]) if rest else ["None."]
    out = write_machine(ctx.vfs, ctx.vfs.path("Studies", f"{name}.md"), fields, "\n".join(lines) + "\n")
    result.add("Studies", out, ctx.vfs)


def _export_studies(ctx: _Ctx, result: ExportResult, study_files: dict[str, str]) -> None:
    for name, filename in study_files.items():
        try:
            _study_note(ctx, result, name, filename)
        except Exception:
            result.errors += 1
            log.exception("Vault: study note %s failed", name)


def _read_package_text(path: str) -> str:
    with open(path, "rb") as f:
        return f.read().decode("utf-8").replace("\r\n", "\n")


def _export_static(ctx: _Ctx, result: ExportResult) -> None:
    vfs = ctx.vfs
    _guard(result, "working paper", lambda: result.add(
        "Paper", write_copy(vfs, vfs.path("Paper", "working-paper.md"), _read_package_text(WORKING_PAPER)), vfs))
    for name in sorted(os.listdir(BASES_DIR)):
        if name.endswith(".base"):
            _guard(result, f"base {name}", lambda n=name: result.add(
                "Bases", write_copy(vfs, vfs.path("Bases", n), _read_package_text(os.path.join(BASES_DIR, n))), vfs))
    for src, dst in (("vault_agents.md", "AGENTS.md"), ("vault_claude.md", "CLAUDE.md")):
        _guard(result, dst, lambda s=src, d=dst: result.add(
            "Root", write_copy(vfs, vfs.path(d), _read_package_text(os.path.join(STATIC_DIR, s))), vfs))


def _export_newsletter(ctx: _Ctx, result: ExportResult) -> None:
    for meta in newsletter.list_issues(ctx.data_dir):
        iid = meta.get("id")
        try:
            path = ctx.vfs.path("Newsletter", f"{iid}.md")
            if ctx.vfs.read_bytes(path) is not None:  # immutable once written: don't even re-read the archive
                result.add("Newsletter", Outcome("unchanged", path), ctx.vfs)
                continue
            md = newsletter.load_text(ctx.data_dir, iid, "md")
            if md is None:
                continue
            fields = [
                ("type", "newsletter"), ("source", SOURCE),
                ("generated_at", str(meta.get("generated_at")) if meta.get("generated_at") else ctx.generated_at),
                ("issue_id", iid), ("week_start", str(meta.get("week_start")) if meta.get("week_start") else None),
                ("week_end", str(meta.get("week_end")) if meta.get("week_end") else None),
                ("tags", ["undertow/newsletter"]),
            ]
            result.add("Newsletter", write_once(ctx.vfs, path, fm.emit(fields) + "\n" + md.replace("\r\n", "\n")), ctx.vfs)
        except Exception:
            result.errors += 1
            log.exception("Vault: newsletter issue %s failed", iid)


def _export_index(ctx: _Ctx, result: ExportResult) -> None:
    vfs = ctx.vfs
    lines = ["", "# Undertow", "",
             "Machine-generated by Undertow. Read [[Undertow/AGENTS|AGENTS]] for the schema and the rules. "
             "Write your own notes outside this folder, or under `## My notes` in a note.", "",
             "| Folder | Notes |", "|---|---|"]
    listing: dict[str, list[str]] = {}
    total = 0
    for folder in FOLDERS:
        names = [n for n in vfs.listdir(folder) if n.endswith((".md", ".base"))]
        listing[folder] = names
        total += len(names)
        lines.append(f"| {folder} | {len(names)} |")
    n_conflicts = len([n for n in vfs.listdir(CONFLICTS) if n.endswith(".md")])
    lines.append(f"| {CONFLICTS} | {n_conflicts} |")
    for folder in FOLDERS:
        names = listing[folder]
        if not names:
            continue
        if folder == "Journal":
            names = sorted(names, key=lambda n: (len(n), n), reverse=True)
        elif folder in ("Signals", "Briefs", "Newsletter"):
            names = sorted(names, reverse=True)
        lines += ["", f"## {folder}", ""]
        for n in names[:INDEX_LINKS]:
            target = n[:-3] if n.endswith(".md") else n
            label = target if n.endswith(".md") else n[:-5]
            lines.append(f"- [[Undertow/{folder}/{target}|{label}]]")
        if len(names) > INDEX_LINKS:
            lines.append(f"- … {len(names) - INDEX_LINKS} more (newest shown)")
    if n_conflicts:
        lines += ["", f"## {CONFLICTS}", "", f"{n_conflicts} conflict file(s): a generated block was edited by hand. "
                  "Merge and delete them yourself; Undertow never deletes anything."]
    fields = [("type", "index"), ("source", SOURCE), ("generated_at", ctx.generated_at), ("notes_total", total),
              ("conflicts", n_conflicts), ("tags", ["undertow/index"])]
    result.add("Root", write_machine(vfs, vfs.path("index.md"), fields, "\n".join(lines) + "\n"), vfs)


# --- state -------------------------------------------------------------------------------------------------------


def _write_state(data_dir: str, result: ExportResult) -> None:
    os.makedirs(data_dir, exist_ok=True)
    payload = {"last_export": result.to_dict(), "written_at": iso_utc(datetime.now(timezone.utc))}
    fd, tmp = tempfile.mkstemp(dir=data_dir, prefix=".vault_state-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp, os.path.join(data_dir, STATE_FILE))


def read_state(data_dir: str) -> dict | None:
    """Last export result as written to {data_dir}/vault_state.json, or None."""
    data = _read_json(os.path.join(data_dir, STATE_FILE))
    return data if isinstance(data, dict) else None


def count_conflicts(vault_dir: str) -> int:
    """Number of conflict files waiting in <vault_dir>/Undertow/_conflicts/."""
    try:
        return len([n for n in VaultFS(vault_dir).listdir(CONFLICTS) if n.endswith(".md")])
    except Exception:
        return 0


# --- entry point -------------------------------------------------------------------------------------------------


def export_vault(
    session: Session,
    *,
    vault_dir: str,
    data_dir: str,
    lookback_days: int = 30,
    evidence_fn: EvidenceFn | None = None,
    paper_fn: PaperFn | None = None,
    study_files: dict[str, str] | None = None,
    now: datetime | None = None,
) -> ExportResult:
    """Write/refresh the Undertow/ folder of the vault. Never raises for one bad note (counted in `errors`)."""
    now = _aware(now) or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    result = ExportResult(started_at=datetime.now(timezone.utc))
    vfs = VaultFS(vault_dir)
    try:
        vfs.ensure_root()
    except Exception:
        result.errors += 1
        log.exception("Vault: cannot use %s", vault_dir)
        result.finished_at = datetime.now(timezone.utc)
        _guard(result, "vault state", _write_state, data_dir, result)
        return result

    ctx = _Ctx(session, vfs, data_dir, lookback_days, evidence_fn, paper_fn, now)

    def load() -> None:
        ctx.articles = [
            a for a in session.scalars(
                select(Article).where(Article.severity.is_not(None), Article.published_at >= ctx.since)
                .order_by(Article.published_at, Article.id)
            ).all()
            if _codes(a) and _aware(a.published_at) <= now
        ]
        ctx.companies = {c.symbol.upper(): c for c in session.scalars(select(Company)).all()}
        ctx.entries = list(session.scalars(select(JournalEntry).order_by(JournalEntry.id)).all())
        ctx.journal_by_article = {e.article_id: e for e in ctx.entries}
        ctx.chain = _chain_days(data_dir)

    _guard(result, "loading data", load)
    _export_static(ctx, result)
    _guard(result, "signals", _export_signals, ctx, result)
    _guard(result, "tickers", _export_tickers, ctx, result)
    _guard(result, "journal", _export_journal, ctx, result)
    _guard(result, "briefs", _export_briefs, ctx, result)
    _guard(result, "studies", _export_studies, ctx, result, study_files if study_files is not None else DEFAULT_STUDY_FILES)
    _guard(result, "newsletter", _export_newsletter, ctx, result)
    _guard(result, "index", _export_index, ctx, result)

    result.finished_at = datetime.now(timezone.utc)
    if result.changed:
        _guard(result, "log", lambda: vfs.append_line(
            vfs.path("log.md"),
            f"- {iso_utc(result.finished_at)} created={result.created} updated={result.updated} "
            f"unchanged={result.unchanged} conflicts={result.conflicts} errors={result.errors}",
            header=LOG_HEADER,
        ))
    if result.conflicts or result.errors:
        log.warning("Vault export: %s", {k: v for k, v in result.to_dict().items() if k != "counts"})
    _guard(result, "vault state", _write_state, data_dir, result)
    return result
