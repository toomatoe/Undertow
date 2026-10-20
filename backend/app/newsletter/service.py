"""Weekly newsletter, "Small-Cap Filing Radar", built automatically from our own data.

`build_issue()` gathers one week (7 ET calendar days ending `week_end`, normally a Sunday) into a
plain dict; `render_markdown()` / `render_html()` turn that dict into text for Substack/Beehiiv or
an email body. `generate()` saves `{data_dir}/newsletters/{id}.json|.md|.html` and never rewrites
an existing issue unless `force=True`: a published issue is a record, like the journal.

Content rules (see frontend/AGENTS.md "Content rules"): impersonal facts and historical statistics
only, every Edge Lab / backtest / track-record number labelled historical or hypothetical, no
recommendations. `banned_words()` is the guard used by tests and by the research-note trimmer.
"""

import html
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fundamentals import service as fundamentals
from app.journal import digest as journal_digest
from app.journal import service as journal
from app.models import Article, Company, JournalEntry, TradingHalt
from app.pipeline.signals import signal_def
from app.research.eventstudy import ET, RESULTS_FILE
from app.sources.halts import REASONS, SERIOUS

log = logging.getLogger(__name__)

TITLE = "Small-Cap Filing Radar"
SMALL = ("nano", "micro", "small")
EVIDENCE_HORIZON = 20
TOP_LIMIT = 20
HALT_LIMIT = 30
DILUTION_LIMIT = 20
PROFILE_LOOKUPS = 15  # company_profile caches daily, but a cold cache is 2 SEC requests each
RUNWAY_MONTHS = 6
RUNWAY_STALE_DAYS = 400  # older cash figures (company stopped filing XBRL) are shown but never qualify
MIN_TRACK_N = 5
NOTE_MAX_CHARS = 520
OFFERING_SIGNALS = {"offering_priced", "offering_registered", "shelf_registered", "unregistered_equity"}
ISSUE_ID = re.compile(r"^\d{4}-W\d{2}$")
# Word stems, so inflections (profitable, selling, buys, targets, opportunities) are caught too.
BANNED = re.compile(r"\b(buy\w*|sell\w*|short it|target\w*|opportunit\w*|guarantee\w*|profit\w*)\b", re.I)

SOURCES_NOTE = "Generated automatically every Monday from public SEC/FINRA/Nasdaq data."
DISCLAIMER = [
    "Research and information only. Everything here is general, impersonal information about public SEC filings, "
    "FINRA data and Nasdaq trading halts. It is not investment, legal or tax advice and not a recommendation about any security.",
    "Edge Lab, backtest and track-record figures are historical and hypothetical: no real trades were made, they are "
    "prepared with hindsight, they cannot fully model real-world costs, and past results are no indication of future results.",
    "Small-cap and nano-cap stocks are volatile and illiquid, and automated classification can misread filings. "
    "Read the original filing, linked from every item, before relying on anything here.",
    "Our trading policy: Afterfile and its operators do not trade any security within 48 hours before or after we publish "
    "an alert or analysis about it, and we accept no payment to cover, promote or omit companies.",
]


# --- helpers -----------------------------------------------------------------------


def banned_words(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in BANNED.finditer(text)})


def issue_id(week_end: date) -> str:
    y, w, _ = week_end.isocalendar()
    return f"{y}-W{w:02d}"


def today_et(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(ET).date()


def last_completed_week_end(today: date) -> date:
    """The most recent Sunday strictly before `today` (on Monday that is yesterday)."""
    return today - timedelta(days=today.weekday() + 1)


def current_week_end(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return _aware(dt).isoformat() if dt else None


def _money(v: float | None) -> str:
    if v is None:
        return "n/a"
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v / 1e3:.0f}K"


def _et(iso: str | None) -> str:
    if not iso:
        return "n/a"
    d = datetime.fromisoformat(iso).astimezone(ET)
    return f"{d:%a %b} {d.day}, {d:%I:%M %p}".replace(" 0", " ") + " ET"


def _day(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}, {d.year}"


def _add_weekdays(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _read_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        log.warning("Could not read %s", path)
        return None


def _study(data_dir: str) -> dict | None:
    return _read_json(os.path.join(data_dir, RESULTS_FILE))


def _sig(code: str) -> dict:
    s = signal_def(code)
    return {"code": code, "label": s.label if s else code, "direction": s.direction if s else "?", "severity": s.severity if s else 1}


# --- build -------------------------------------------------------------------------


def _window(week_end: date, now: datetime | None) -> tuple[datetime, datetime, bool]:
    start = datetime.combine(week_end - timedelta(days=6), time(0), ET).astimezone(timezone.utc)
    end = datetime.combine(week_end + timedelta(days=1), time(0), ET).astimezone(timezone.utc)
    if now is not None and _aware(now) < end:
        return start, _aware(now), True
    return start, end, False


def _filings(session: Session, start: datetime, end: datetime) -> list[tuple[Article, Company]]:
    """Signal filings in the window whose company is a small cap, oldest first, one company per filing."""
    rows = session.scalars(
        select(Article)
        .where(Article.severity.is_not(None), Article.published_at >= start, Article.published_at < end)
        .order_by(Article.published_at, Article.id)
    ).all()
    symbols = {t.symbol for a in rows for t in a.tickers}
    companies = {
        c.symbol: c
        for c in session.scalars(select(Company).where(Company.symbol.in_(symbols), Company.size_bucket.in_(SMALL)))
    } if symbols else {}
    out = []
    for a in rows:
        tickers = sorted(a.tickers, key=lambda t: t.method != "edgar")
        company = next((companies[t.symbol] for t in tickers if t.symbol in companies), None)
        if company is not None and a.signals:
            out.append((a, company))
    return out


def _evidence_index(study: dict | None) -> dict[tuple[str, str], dict]:
    if not study:
        return {}
    return {
        (r["signal"], r["bucket"]): {k: r.get(k) for k in ("n", "horizon_days", "mean_abnormal", "median_abnormal", "excess_vs_baseline", "t_stat", "significant")}
        for r in study.get("results", [])
        if r.get("horizon_days") == EVIDENCE_HORIZON
    }


def _filing_item(a: Article, c: Company, evidence: dict) -> dict:
    sigs = [_sig(code) for code in a.signals]
    ev = next(({**evidence[(s["code"], c.size_bucket)], "signal": s["code"], "label": s["label"]}
               for s in sigs if (s["code"], c.size_bucket) in evidence), None)
    return {
        "article_id": a.id,
        "ticker": c.symbol,
        "company": c.name or a.title.split(": ", 1)[-1],
        "size": c.size_bucket,
        "public_float": c.public_float,
        "form": a.form,
        "severity": a.severity,
        "signals": sigs,
        "filed_at": _iso(a.published_at),
        "url": a.url,
        "evidence": ev,
    }


def _dilution_watch(filings: list[tuple[Article, Company]], data_dir: str, user_agent: str | None, as_of: date) -> tuple[list[dict], int]:
    groups: dict[str, dict] = {}
    for a, c in filings:
        offering = [s for s in a.signals if s in OFFERING_SIGNALS]
        if not offering:
            continue
        g = groups.setdefault(c.symbol, {"company": c, "count": 0, "priced": False, "filings": [], "last": a.published_at})
        g["count"] += len(offering)
        g["priced"] |= "offering_priced" in offering
        g["last"] = max(_aware(g["last"]), _aware(a.published_at))
        g["filings"].append({"form": a.form, "signals": [_sig(s)["label"] for s in offering], "filed_at": _iso(a.published_at), "url": a.url})

    # Runway lookups: priced offerings first (they can qualify on runway alone), then repeat filers
    order = sorted(groups, key=lambda s: (not groups[s]["priced"], -groups[s]["count"], -_aware(groups[s]["last"]).timestamp()))
    lookups = 0
    for sym in order:
        g = groups[sym]
        g["runway"] = None
        if lookups >= PROFILE_LOOKUPS or not (g["priced"] or g["count"] >= 2):
            continue
        lookups += 1
        try:
            prof = fundamentals.company_profile(g["company"].cik, data_dir, user_agent or "")
        except Exception as exc:  # SEC down or odd XBRL: the section still works without runway
            log.warning("Newsletter runway lookup failed for %s: %s", sym, exc)
            continue
        rw = (prof or {}).get("runway") or {}
        cash_as_of = ((prof or {}).get("cash") or {}).get("as_of")
        stale = bool(cash_as_of and (as_of - date.fromisoformat(cash_as_of[:10])).days > RUNWAY_STALE_DAYS)
        g["runway"] = {"status": rw.get("status", "unknown"), "months": rw.get("months"),
                       "runs_out_around": rw.get("runs_out_around"), "cash_as_of": cash_as_of, "stale": stale}

    out = []
    for sym in order:
        g = groups[sym]
        rw = g["runway"]
        short_runway = bool(g["priced"] and rw and not rw.get("stale") and rw["status"] == "burning" and rw["months"] is not None and rw["months"] < RUNWAY_MONTHS)
        reasons = []
        if g["count"] >= 2:
            reasons.append(f"{g['count']} offering-type filings this week")
        if short_runway:
            reasons.append(f"priced offering with reported cash runway under {RUNWAY_MONTHS} months")
        if not reasons:
            continue
        c = g["company"]
        out.append({"ticker": sym, "company": c.name, "size": c.size_bucket, "public_float": c.public_float,
                    "offering_signals": g["count"], "priced": g["priced"], "filings": g["filings"], "runway": rw, "reasons": reasons})
    return out[:DILUTION_LIMIT], lookups


def _halts(session: Session, start: datetime, end: datetime) -> list[dict]:
    rows = session.scalars(
        select(TradingHalt)
        .where(TradingHalt.halted_at >= start, TradingHalt.halted_at < end, TradingHalt.reason_code.in_(sorted(SERIOUS)))
        .order_by(TradingHalt.halted_at)
    ).all()
    sizes = dict(session.execute(select(Company.symbol, Company.size_bucket).where(Company.symbol.in_({h.symbol for h in rows}))).all()) if rows else {}
    return [
        {"symbol": h.symbol, "name": h.name, "market": h.market, "reason_code": h.reason_code,
         "reason": REASONS.get(h.reason_code, h.reason_code), "halted_at": _iso(h.halted_at),
         "resumed_at": _iso(h.resumed_at), "size": sizes.get(h.symbol)}
        for h in rows
        if sizes.get(h.symbol) not in ("mid", "large")  # small caps, plus names with no float on file
    ]


def _track_record(session: Session, study: dict | None, data_dir: str) -> dict:
    expected = {(r["signal"], r["bucket"], r["horizon_days"]): r for r in (study or {}).get("results", [])}
    rows = [r for r in journal.summary(session, expected) if r["bucket"] in SMALL]
    keep = ("signal", "label", "direction", "bucket", "n", "n_20", "mean_20", "median_20", "hit_20", "expected_20")
    mature = [{k: r[k] for k in keep} for r in rows if r["n_20"] >= MIN_TRACK_N]
    recorded = session.scalar(select(func.count(JournalEntry.id))) or 0
    complete = session.scalar(select(func.count(JournalEntry.id)).where(JournalEntry.abn_20.is_not(None))) or 0
    collecting = None
    if not mature:
        first = session.scalar(
            select(func.min(JournalEntry.filed_at)).where(JournalEntry.abn_20.is_(None), JournalEntry.status.in_(["waiting", "open"]))
        )
        due = _add_weekdays(_aware(first).astimezone(ET).date(), journal.ENTRY_DELAY + EVIDENCE_HORIZON).isoformat() if first else None
        collecting = {"recorded": recorded, "first_due": due}
    return {"recorded": recorded, "complete_20d": complete, "min_n": MIN_TRACK_N,
            "rows": sorted(mature, key=lambda r: -r["n_20"]), "collecting": collecting,
            "seal": journal_digest.chain_head(data_dir)}  # {head_hash, head_day, days} of the journal hash chain, or None


def _coverage_note(session: Session, start: datetime, end: datetime) -> str | None:
    """Say so when live filing collection began after the week started (an empty week is then not a quiet week)."""
    first = _aware(session.scalar(select(func.min(Article.published_at)).where(Article.severity.is_not(None))))
    if first is None:
        return "Live filing collection has not started yet, so this issue has no filing data."
    if first <= start:
        return None
    when = first.astimezone(ET).date()
    if first >= end:
        return f"Live filing collection began {when:%b} {when.day}, {when.year}, after this week ended, so this issue has no filing data."
    return f"Live filing collection began {when:%b} {when.day}, {when.year}, so this week is only partly covered."


def _research_note(data_dir: str) -> dict | None:
    report = _read_json(os.path.join(data_dir, "backtests", "report_latest.json"))
    text = ((report or {}).get("key_finding") or {}).get("text")
    if not text:
        return None
    kept, dropped = "", 0
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if banned_words(sentence):
            dropped += 1
            continue
        if kept and len(kept) + len(sentence) > NOTE_MAX_CHARS:
            break
        kept = f"{kept} {sentence}".strip()
    log.info("Newsletter research note: dropped %d sentence(s) with banned words", dropped)
    if not kept:
        return None
    return {"text": kept, "strategy": ((report.get("strategy") or {}).get("name")), "report_date": (report.get("generated_at") or "")[:10] or None}


def build_issue(
    session: Session,
    data_dir: str,
    week_end: date,
    *,
    user_agent: str | None = None,
    public_base_url: str = "http://localhost:3000",
    now: datetime | None = None,
) -> dict:
    """One issue covering the 7 ET calendar days ending `week_end` (cut off at `now` for a preview)."""
    start, end, partial = _window(week_end, now)
    base = public_base_url.rstrip("/")
    study = _study(data_dir)
    evidence = _evidence_index(study)
    filings = _filings(session, start, end)
    items = [_filing_item(a, c, evidence) for a, c in filings]
    top = sorted((i for i in items if (i["severity"] or 0) >= 2), key=lambda i: i["filed_at"], reverse=True)
    top.sort(key=lambda i: -i["severity"])  # stable: severity 3 first, newest first within each level
    dilution, lookups = _dilution_watch(filings, data_dir, user_agent, week_end)
    halts = _halts(session, start, end)
    coverage = _coverage_note(session, start, end)

    by_sev = {str(s): sum(1 for i in items if i["severity"] == s) for s in (3, 2, 1)}
    by_size = {b: sum(1 for i in items if i["size"] == b) for b in SMALL}
    iid = issue_id(week_end)
    issue = {
        "id": iid,
        "title": TITLE,
        "week_start": (week_end - timedelta(days=6)).isoformat(),
        "week_end": week_end.isoformat(),
        "partial": partial,
        "data_through": end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "sources_note": SOURCES_NOTE,
        "coverage_note": coverage,
        "headline": {
            "signal_filings": len(items),
            "companies": len({i["ticker"] for i in items}),
            "by_severity": by_sev,
            "by_size": by_size,
            "dilution_watch": len(dilution),
            "serious_halts": len(halts),
        },
        "top_filings": top[:TOP_LIMIT],
        "top_filings_total": len(top),
        "dilution_watch": dilution,
        "runway_lookups": lookups,
        "serious_halts": halts[:HALT_LIMIT],
        "serious_halts_total": len(halts),
        "track_record": _track_record(session, study, data_dir),
        "research_note": _research_note(data_dir),
        "links": {
            "methodology": f"{base}/methodology",
            "track_record": f"{base}/track-record",
            "edge_lab": f"{base}/lab",
            "disclaimer": f"{base}/legal/disclaimer",
            "archive": f"{base}/newsletter?issue={iid}",
        },
        "disclaimer": DISCLAIMER,
    }
    issue["flagged_words"] = flagged_words(issue)
    if issue["flagged_words"]:
        log.error("Newsletter %s prose contains flagged words %s", iid, issue["flagged_words"])
    return issue


def _without_names(issue: dict) -> dict:
    """Copy of the issue with third-party names (company names, halt names, tickers) blanked out.

    Company names and filing titles are data, not our prose: real names like "Sellas" or a ticker
    like "BUYZ" match the banned stems. Only our own text should be flagged.
    """
    def blank(rows: list[dict], *keys: str) -> list[dict]:
        return [{**r, **{k: "X" for k in keys if k in r}} for r in rows]

    return {
        **issue,
        "top_filings": blank(issue.get("top_filings") or [], "company", "ticker"),
        "dilution_watch": blank(issue.get("dilution_watch") or [], "company", "ticker"),
        "serious_halts": blank(issue.get("serious_halts") or [], "name", "symbol"),
    }


def flagged_words(issue: dict) -> list[str]:
    """Banned words in the rendered Markdown + HTML, ignoring company names and filing titles."""
    scrubbed = _without_names(issue)
    return sorted(set(banned_words(render_markdown(scrubbed))) | set(banned_words(render_html(scrubbed))))


# --- text fragments shared by both renderers ---------------------------------------

ARROW = {"-": "▼", "+": "▲", "?": "◆"}
SEV_WORD = {3: "High severity", 2: "Medium severity", 1: "Low severity"}


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1%}"


def ticker_url(issue: dict, symbol: str) -> str:
    return f"{issue['base_url']}/ticker/{quote(symbol)}"


def week_label(issue: dict) -> str:
    s, e = date.fromisoformat(issue["week_start"]), date.fromisoformat(issue["week_end"])
    return f"{s:%b} {s.day} to {e:%b} {e.day}, {e.year}"


def evidence_text(item: dict) -> str | None:
    ev = item.get("evidence")
    if not ev or ev.get("mean_abnormal") is None:
        return None
    excess = f" ({ev['excess_vs_baseline']:+.1%} vs the same stocks' ordinary days)" if ev.get("excess_vs_baseline") is not None else ""
    sig = "significant after multiple-testing correction" if ev.get("significant") else "not statistically significant"
    return (f"Historical, hypothetical: past {item['size']} caps after \"{ev['label']}\" moved {ev['mean_abnormal']:+.1%} on average "
            f"vs the index over {ev['horizon_days']} trading days{excess}, n={ev['n']}, {sig}.")


def headline_text(issue: dict) -> str:
    h = issue["headline"]
    s = h["by_severity"]
    return (f"{h['signal_filings']} signal filings from {h['companies']} small-cap companies "
            f"({s['3']} high, {s['2']} medium, {s['1']} low severity); "
            f"{h['dilution_watch']} on the dilution watch; {h['serious_halts']} serious trading halts.")


def runway_text(rw: dict | None) -> str:
    if not rw:
        return "runway not looked up"
    if rw.get("stale") and rw.get("cash_as_of"):
        return f"latest reported cash is from {_day(rw['cash_as_of'])}, too old to estimate runway"
    if rw["status"] == "burning" and rw.get("months") is not None:
        asof = f" as of {_day(rw['cash_as_of'])}" if rw.get("cash_as_of") else ""
        return f"reported cash covers about {rw['months']:.1f} months of operating burn{asof}, before any later raise"
    if rw["status"] == "cash_flow_positive":
        return "operating cash flow positive (trailing 12 months)"
    return "runway not reported in XBRL"


def track_lines(issue: dict) -> list[str]:
    tr = issue["track_record"]
    if tr["collecting"] is not None:
        c = tr["collecting"]
        due = f", first 20-day results due ~{_day(c['first_due'])}" if c.get("first_due") else ""
        return [f"Still collecting: {c['recorded']} signals recorded{due}. Groups are shown once they have {tr['min_n']}+ 20-day results."]
    lines = []
    for r in tr["rows"]:
        hit = f", {r['hit_20']:.0%} moved in the expected direction" if r.get("hit_20") is not None and r["direction"] != "?" else ""
        exp = f"; Edge Lab historical mean {_pct(r['expected_20'])}" if r.get("expected_20") is not None else ""
        lines.append(f"{ARROW.get(r['direction'], '◆')} {r['label']} ({r['bucket']} caps): n={r['n_20']}, mean {_pct(r['mean_20'])} "
                     f"vs IWM over 20 trading days (median {_pct(r['median_20'])}{hit}){exp}.")
    return lines


def seal_line(issue: dict) -> str | None:
    """One line naming the journal hash-chain head at build time (None when no chain, or an issue archived before seals)."""
    seal = (issue.get("track_record") or {}).get("seal")
    if not seal:
        return None
    return (f"Track-record seal through {seal['head_day']}: {seal['head_hash'][:16]}… "
            f"({seal['days']} days; verify at {issue['links']['track_record']})")


# --- Markdown ----------------------------------------------------------------------


def _md_escape(s: str) -> str:
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", s or "")


def render_markdown(issue: dict) -> str:
    L = issue["links"]
    out = [f"# {issue['title']}: {week_label(issue)}", ""]
    if issue["partial"]:
        out += [f"*Preview: week in progress, data through {_et(issue['data_through'])}.*", ""]
    out += [f"*{issue['sources_note']} Impersonal facts and historical statistics; not investment advice.*", ""]

    out += ["## This week in numbers", "", headline_text(issue), ""]
    if issue.get("coverage_note"):
        out += [f"*{issue['coverage_note']}*", ""]
    h = issue["headline"]
    out += [f"- Nano caps: {h['by_size']['nano']} · Micro caps: {h['by_size']['micro']} · Small caps: {h['by_size']['small']}", ""]

    out += ["## Top filings this week", ""]
    if not issue["top_filings"]:
        out += ["No high- or medium-severity signal filings from small caps this week.", ""]
    for i in issue["top_filings"]:
        sigs = ", ".join(f"{ARROW[s['direction']]} {s['label']}" for s in i["signals"])
        out.append(f"### [{i['ticker']}]({ticker_url(issue, i['ticker'])}) · {_md_escape(i['company'])}")
        out.append(f"{SEV_WORD.get(i['severity'], '')} · {i['size']} cap, float {_money(i['public_float'])} · "
                   f"Form {i['form'] or 'n/a'} · filed {_et(i['filed_at'])} · [filing]({i['url']})")
        out.append("")
        out.append(f"Signals: {sigs}")
        if ev := evidence_text(i):
            out += ["", f"> {ev}"]
        out.append("")
    if issue["top_filings_total"] > len(issue["top_filings"]):
        out += [f"*Plus {issue['top_filings_total'] - len(issue['top_filings'])} more high- or medium-severity filings.*", ""]

    out += ["## Dilution watch", "", f"Companies with 2+ offering-type filings this week, or a priced offering with reported cash runway under {RUNWAY_MONTHS} months.", ""]
    if not issue["dilution_watch"]:
        out += ["None this week.", ""]
    for d in issue["dilution_watch"]:
        filings = "; ".join(f"[{_md_escape(f['form'] or 'filing')}]({f['url']}) {_et(f['filed_at'])}" for f in d["filings"])
        out.append(f"- **[{d['ticker']}]({ticker_url(issue, d['ticker'])})** {_md_escape(d['company'])} ({d['size']} cap, float {_money(d['public_float'])}): "
                   f"{'; '.join(d['reasons'])}. Runway: {runway_text(d['runway'])}. Filings: {filings}")
    out.append("")

    out += ["## Serious trading halts", ""]
    if not issue["serious_halts"]:
        out += ["No news-pending or regulatory halts for small caps this week.", ""]
    for x in issue["serious_halts"]:
        resumed = f", resumed {_et(x['resumed_at'])}" if x.get("resumed_at") else ", no resumption time on file"
        out.append(f"- **{x['symbol']}** {_md_escape(x['name'])} ({x['size'] or 'size unknown'}): {x['reason']} ({x['reason_code']}), "
                   f"halted {_et(x['halted_at'])}{resumed}")
    if issue["serious_halts_total"] > len(issue["serious_halts"]):
        out.append(f"- Plus {issue['serious_halts_total'] - len(issue['serious_halts'])} more.")
    out.append("")

    out += ["## Track record update", "", "*Simulated forward tracking of every signal as filed; no trades. "
            f"[Full track record]({L['track_record']}).*", ""]
    out += [f"- {line}" for line in track_lines(issue)]
    if seal := seal_line(issue):
        out += ["", f"*{_md_escape(seal)}*"]
    out.append("")

    if note := issue.get("research_note"):
        src = f" (\"{note['strategy']}\", report of {_day(note['report_date'])})" if note.get("strategy") and note.get("report_date") else ""
        out += ["## Research note", "", f"*From our hypothetical backtest{src}. Simulated results, not real trading.*", "", note["text"], ""]

    out += ["---", "", f"How every number is produced: [Methodology]({L['methodology']}) · [Edge Lab]({L['edge_lab']}) · "
            f"[Disclaimer]({L['disclaimer']}) · [Archive]({L['archive']})", ""]
    for p in issue["disclaimer"]:
        out += [f"*{p}*", ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


# --- Email-safe HTML ---------------------------------------------------------------

FONT = "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
C_TEXT, C_MUTED, C_BORDER, C_LINK = "#12161d", "#5f6878", "#dfe3ea", "#1d5fc0"
C_DIR = {"-": "#b42318", "+": "#1d5fc0", "?": "#5f6878"}


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _a(url: str, text: str) -> str:
    return f'<a href="{_e(url)}" style="color:{C_LINK};text-decoration:underline;">{_e(text)}</a>'


def _row(inner: str, pad: str = "0 24px 16px") -> str:
    return f'<tr><td style="padding:{pad};{FONT}font-size:14px;line-height:1.5;color:{C_TEXT};">{inner}</td></tr>'


def _h2(text: str) -> str:
    return _row(f'<h2 style="margin:0;padding:12px 0 6px;border-top:1px solid {C_BORDER};font-size:16px;color:{C_TEXT};">{_e(text)}</h2>', "8px 24px 4px")


def _p(text_html: str, muted: bool = False, size: int = 14) -> str:
    color = C_MUTED if muted else C_TEXT
    return f'<p style="margin:0 0 8px;font-size:{size}px;color:{color};">{text_html}</p>'


def _arrow(d: str) -> str:
    return f'<span style="color:{C_DIR.get(d, C_MUTED)};">{ARROW.get(d, "◆")}</span>'


def render_html(issue: dict) -> str:
    L = issue["links"]
    rows = [
        _row(f'<div style="font-size:12px;color:{C_MUTED};text-transform:uppercase;letter-spacing:.05em;">Afterfile weekly</div>'
             f'<h1 style="margin:4px 0 2px;font-size:22px;color:{C_TEXT};">{_e(issue["title"])}</h1>'
             f'<div style="font-size:14px;color:{C_MUTED};">{_e(week_label(issue))}</div>', "24px 24px 12px"),
    ]
    if issue["partial"]:
        rows.append(_row(_p(f"<em>Preview: week in progress, data through {_e(_et(issue['data_through']))}.</em>", muted=True)))
    rows.append(_row(_p(_e(issue["sources_note"] + " Impersonal facts and historical statistics; not investment advice."), muted=True, size=12)))

    h = issue["headline"]
    rows.append(_h2("This week in numbers"))
    cells = "".join(
        f'<td width="25%" style="padding:8px;border:1px solid {C_BORDER};{FONT}text-align:center;">'
        f'<div style="font-size:20px;font-weight:700;color:{C_TEXT};">{v}</div><div style="font-size:11px;color:{C_MUTED};">{_e(k)}</div></td>'
        for k, v in (("Signal filings", h["signal_filings"]), ("High severity", h["by_severity"]["3"]),
                     ("Dilution watch", h["dilution_watch"]), ("Serious halts", h["serious_halts"]))
    )
    rows.append(_row(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;"><tr>{cells}</tr></table>'))
    rows.append(_row(_p(_e(headline_text(issue)), muted=True, size=13)))
    if issue.get("coverage_note"):
        rows.append(_row(_p(f"<em>{_e(issue['coverage_note'])}</em>", muted=True, size=12)))

    rows.append(_h2("Top filings this week"))
    if not issue["top_filings"]:
        rows.append(_row(_p("No high- or medium-severity signal filings from small caps this week.", muted=True)))
    for i in issue["top_filings"]:
        sigs = " &nbsp; ".join(f"{_arrow(s['direction'])} {_e(s['label'])}" for s in i["signals"])
        ev = evidence_text(i)
        inner = (
            f'<div style="font-size:15px;font-weight:700;">{_a(ticker_url(issue, i["ticker"]), i["ticker"])} '
            f'<span style="font-weight:400;color:{C_TEXT};">{_e(i["company"])}</span></div>'
            f'<div style="font-size:12px;color:{C_MUTED};margin:2px 0 4px;">{_e(SEV_WORD.get(i["severity"], ""))} · {_e(i["size"])} cap, '
            f'float {_e(_money(i["public_float"]))} · Form {_e(i["form"] or "n/a")} · filed {_e(_et(i["filed_at"]))} · {_a(i["url"], "filing")}</div>'
            f'<div style="font-size:13px;">{sigs}</div>'
            + (f'<div style="font-size:12px;color:{C_MUTED};margin-top:4px;padding-left:8px;border-left:3px solid {C_BORDER};">{_e(ev)}</div>' if ev else "")
        )
        rows.append(_row(inner, "0 24px 14px"))
    if issue["top_filings_total"] > len(issue["top_filings"]):
        rows.append(_row(_p(f"Plus {issue['top_filings_total'] - len(issue['top_filings'])} more high- or medium-severity filings.", muted=True, size=12)))

    rows.append(_h2("Dilution watch"))
    rows.append(_row(_p(f"Companies with 2+ offering-type filings this week, or a priced offering with reported cash runway under {RUNWAY_MONTHS} months.", muted=True, size=12)))
    if not issue["dilution_watch"]:
        rows.append(_row(_p("None this week.", muted=True)))
    for d in issue["dilution_watch"]:
        filings = "; ".join(f"{_a(f['url'], f['form'] or 'filing')} {_e(_et(f['filed_at']))}" for f in d["filings"])
        rows.append(_row(
            f'<div><strong>{_a(ticker_url(issue, d["ticker"]), d["ticker"])}</strong> {_e(d["company"])} '
            f'<span style="color:{C_MUTED};">({_e(d["size"])} cap, float {_e(_money(d["public_float"]))})</span></div>'
            f'<div style="font-size:13px;">{_e("; ".join(d["reasons"]))}. Runway: {_e(runway_text(d["runway"]))}.</div>'
            f'<div style="font-size:12px;color:{C_MUTED};">Filings: {filings}</div>', "0 24px 12px"))

    rows.append(_h2("Serious trading halts"))
    if not issue["serious_halts"]:
        rows.append(_row(_p("No news-pending or regulatory halts for small caps this week.", muted=True)))
    for x in issue["serious_halts"]:
        resumed = f"resumed {_et(x['resumed_at'])}" if x.get("resumed_at") else "no resumption time on file"
        rows.append(_row(
            f'<div><strong>{_e(x["symbol"])}</strong> {_e(x["name"])} <span style="color:{C_MUTED};">({_e(x["size"] or "size unknown")})</span></div>'
            f'<div style="font-size:12px;color:{C_MUTED};">{_e(x["reason"])} ({_e(x["reason_code"])}) · halted {_e(_et(x["halted_at"]))} · {_e(resumed)}</div>',
            "0 24px 10px"))
    if issue["serious_halts_total"] > len(issue["serious_halts"]):
        rows.append(_row(_p(f"Plus {issue['serious_halts_total'] - len(issue['serious_halts'])} more.", muted=True, size=12)))

    rows.append(_h2("Track record update"))
    rows.append(_row(_p(f"Simulated forward tracking of every signal as filed; no trades. {_a(L['track_record'], 'Full track record')}.", muted=True, size=12)))
    for line in track_lines(issue):
        rows.append(_row(_p(_e(line), size=13), "0 24px 6px"))
    if seal := seal_line(issue):
        rows.append(_row(_p(_e(seal), muted=True, size=12), "0 24px 6px"))

    if note := issue.get("research_note"):
        src = f" (“{note['strategy']}”, report of {_day(note['report_date'])})" if note.get("strategy") and note.get("report_date") else ""
        rows.append(_h2("Research note"))
        rows.append(_row(_p(f"<em>{_e('From our hypothetical backtest' + src + '. Simulated results, not real trading.')}</em>", muted=True, size=12)
                         + _p(_e(note["text"]))))

    links = " · ".join(_a(L[k], t) for k, t in (("methodology", "Methodology"), ("edge_lab", "Edge Lab"), ("disclaimer", "Disclaimer"), ("archive", "Archive")))
    rows.append(_row(f'<div style="border-top:1px solid {C_BORDER};padding-top:12px;font-size:13px;">How every number is produced: {links}</div>', "8px 24px 8px"))
    rows.append(_row("".join(_p(_e(p), muted=True, size=11) for p in issue["disclaimer"]), "0 24px 24px"))

    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(issue['title'])}: {_e(week_label(issue))}</title></head>\n"
        f'<body style="margin:0;padding:0;background:#f4f5f7;">\n'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f5f7;">'
        f'<tr><td align="center" style="padding:24px 8px;">\n'
        f'<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;max-width:640px;background:#ffffff;border:1px solid {C_BORDER};border-radius:8px;">\n'
        + "\n".join(rows)
        + "\n</table>\n</td></tr></table>\n</body></html>\n"
    )


# --- storage -----------------------------------------------------------------------


def issue_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "newsletters")


def _path(data_dir: str, iid: str, ext: str) -> str:
    if not ISSUE_ID.match(iid):
        raise ValueError(f"Bad issue id {iid!r}")
    return os.path.join(issue_dir(data_dir), f"{iid}.{ext}")


def exists(data_dir: str, iid: str) -> bool:
    return os.path.exists(_path(data_dir, iid, "json"))


def save_issue(issue: dict, data_dir: str) -> None:
    os.makedirs(issue_dir(data_dir), exist_ok=True)
    md, page = render_markdown(issue), render_html(issue)
    # build_issue already scanned our prose (names excluded) into issue["flagged_words"] and logged at error level.
    # Logged, not refused: refusing would block the week forever.
    for ext, text in (("md", md), ("html", page)):
        with open(_path(data_dir, issue["id"], ext), "w", encoding="utf-8") as f:
            f.write(text)
    tmp = _path(data_dir, issue["id"], "json") + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(issue, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(data_dir, issue["id"], "json"))  # JSON last: its presence means the issue is complete


def generate(session: Session, data_dir: str, week_end: date, *, force: bool = False, **kw) -> tuple[dict, bool]:
    """Build and save an issue. An existing issue is returned untouched unless force=True."""
    iid = issue_id(week_end)
    if not force and exists(data_dir, iid):
        return load_issue(data_dir, iid), False
    issue = build_issue(session, data_dir, week_end, **kw)
    save_issue(issue, data_dir)
    return issue, True


def ensure_latest(session: Session, data_dir: str, today: date | None = None, **kw) -> str | None:
    """Scheduler hook: build the issue for the last completed week if it doesn't exist. Returns its id if built."""
    week_end = last_completed_week_end(today or today_et())
    if exists(data_dir, issue_id(week_end)):
        return None
    issue, created = generate(session, data_dir, week_end, **kw)
    return issue["id"] if created else None


def preview(session: Session, data_dir: str, now: datetime | None = None, **kw) -> dict:
    """The current week so far. Never saved."""
    now = now or datetime.now(timezone.utc)
    return build_issue(session, data_dir, current_week_end(today_et(now)), now=now, **kw)


def load_issue(data_dir: str, iid: str) -> dict | None:
    try:
        return _read_json(_path(data_dir, iid, "json"))
    except ValueError:
        return None


def load_text(data_dir: str, iid: str, ext: str) -> str | None:
    try:
        path = _path(data_dir, iid, ext)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def list_issues(data_dir: str) -> list[dict]:
    d = issue_dir(data_dir)
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d), reverse=True):
        iid = name.removesuffix(".json")
        if not name.endswith(".json") or not ISSUE_ID.match(iid):
            continue
        issue = load_issue(data_dir, iid)
        if issue:
            out.append({k: issue.get(k) for k in ("id", "title", "week_start", "week_end", "generated_at", "headline")})
    return out
