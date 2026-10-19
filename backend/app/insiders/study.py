"""Form 4 insider-purchase event study (pre-registered in PREREGISTRATION.md, 2026-10-19).

A separate study from the main Edge Lab grid: its own signal taxonomy (SIGNAL_DEFS, never added to
app.pipeline.signals) and its own Bonferroni family. It reuses the main engine unchanged:
eventstudy.run_design(DESIGN, event_source, SIGNAL_DEFS) -> collect() + summarize(signal_defs=...).

Pipeline:
1. datasets.download_quarter / iter_quarter: SEC Insider Transactions Data Sets, joined per row.
2. Pass 1 (event quarters + one quarter of look-back): qualifying purchases (Form 4, P/A, shares and
   price > 0, director or officer, not AFF10B5ONE).
3. Pass 2 (history quarters 2020Q1+): P/S trades of the insiders found in pass 1 -> classify.TradeHistory.
4. build_events(): per issuer per filing date, >= $10,000 -> the four signals. Day 0 is the first close
   after the filing date (event timed 23:59 ET, so eventstudy.day0_index moves it to the next bar).
5. run_design() with an event_source that checks the company (operating, not a SPAC, has a ticker) from the
   cached submissions JSON and yields its insider events. Companies without events still give baseline days.
6. Significance per the pre-registration (clustered t), opportunistic vs routine (descriptive), and a
   dataset-vs-raw-XML cross-check of 50 random events (form4.parse_ownership_xml).

Output: {DATA_DIR}/event_study_insider_purchases.json in the event_study.json schema plus
data_quality, preregistration, opportunistic_vs_routine.

Run:  python -m app.insiders.study [--offline [--allow-missing]] [--output PATH] [--quarters 2024q1 ...]
"""

import argparse
import logging
import math
import os
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import httpx

from app.config import get_settings
from app.insiders import datasets
from app.insiders.classify import HISTORY_CODES, OPPORTUNISTIC, ROUTINE, TradeHistory
from app.insiders.datasets import TransactionRow
from app.insiders.form4 import parse_ownership_xml, raw_xml_url
from app.pipeline.signals import SignalDef
from app.research import snapshot
from app.research.eventstudy import (
    ET,
    EXCLUDED_SIC,
    OFFLINE_MISS,
    RESULTS_FILE,
    SUBMISSIONS_URL,
    Event,
    StudyDesign,
    add_replay_args,
    check_offline_misses,
    get_json,
    log_highlights,
    run_design,
    write_study,
)

log = logging.getLogger("insiders.study")

# --- Pre-registered constants (PREREGISTRATION.md; test_insiders.py checks them) ---------------

PREREGISTRATION = "backend/app/insiders/PREREGISTRATION.md"
PREREGISTERED_ON = "2026-10-19"
INSIDER_RESULTS_FILE = "event_study_insider_purchases.json"
EVENT_START = date(2023, 10, 1)
EVENT_END = date(2026, 6, 30)  # end of 2026Q2, the latest complete quarter
HISTORY_QUARTERS = ((2020, 1), (2026, 2))
EVENT_QUARTERS = ((2023, 4), (2026, 2))
LOOKBACK_QUARTER = (2023, 3)  # cluster look-back for events early in 2023Q4
MIN_VALUE = 10_000.0
CLUSTER_DAYS = 10
CROSSCHECK_N = 50
SEED = 11
SIZES = {"nano": 300, "micro": 400, "small": 400, "large": 100}
DESIGN = StudyDesign(
    name="insider_purchases",
    window_start=EVENT_START,
    window_end=EVENT_END,
    float_year=2023,
    seed=SEED,
    sizes=SIZES,
    results_file=INSIDER_RESULTS_FILE,
)

PURCHASE = "insider_purchase"
CLUSTER = "insider_cluster_purchase"
OPPORTUNISTIC_SIGNAL = "insider_purchase_opportunistic"
ROUTINE_SIGNAL = "insider_purchase_routine"
SIGNAL_DEFS: dict[str, SignalDef] = {
    PURCHASE: SignalDef(PURCHASE, "Insider purchase (director/officer)", "+", 2,
                        "A director or officer reported an open-market purchase of at least $10,000 (Form 4)"),
    CLUSTER: SignalDef(CLUSTER, "Insider cluster purchase", "+", 2,
                       "Two or more different insiders reported purchases within 10 days"),
    OPPORTUNISTIC_SIGNAL: SignalDef(OPPORTUNISTIC_SIGNAL, "Insider purchase, opportunistic (CMP)", "+", 2,
                                    "Purchase by an insider without a same-month trading pattern in the 3 prior years"),
    ROUTINE_SIGNAL: SignalDef(ROUTINE_SIGNAL, "Insider purchase, routine (CMP control)", "+", 1,
                              "Purchase by an insider who traded in the same calendar month in each of the 3 prior years"),
}
_CLASS_SIGNAL = {OPPORTUNISTIC: OPPORTUNISTIC_SIGNAL, ROUTINE: ROUTINE_SIGNAL}
XML_CACHE_SUBDIR = "insider_xml"


# --- Filters ---------------------------------------------------------------------


def insider_cik(row: TransactionRow) -> int | None:
    """Lowest CIK among the filing's director/officer owners (one insider per filing)."""
    ciks = [o.cik for o in row.owners if o.is_director or o.is_officer]
    return min(ciks) if ciks else None


def exclusion_reason(row: TransactionRow) -> str | None:
    """None for a qualifying purchase, else the first filter it fails (counted in data_quality)."""
    if row.document_type != "4":
        return "not_form4"
    if row.code != "P" or row.acquired_disposed != "A":
        return "not_open_market_purchase"
    if not row.shares or row.shares <= 0 or row.price is None:
        return "no_shares_or_price"
    if insider_cik(row) is None:
        return "not_director_or_officer"
    if row.aff10b5one:
        return "aff10b5one"
    return None


def is_qualifying(row: TransactionRow) -> bool:
    return exclusion_reason(row) is None


def day0_datetime(filing_date: date) -> datetime:
    """Event time for a filing date with no acceptance time: after the close, so day 0 is the next bar."""
    return datetime(filing_date.year, filing_date.month, filing_date.day, 23, 59, tzinfo=ET)


# --- Loading ---------------------------------------------------------------------


@dataclass(frozen=True)
class Purchase:
    issuer_cik: int
    insider_cik: int
    filing_date: date
    trans_date: date | None
    value: float
    accession: str


@dataclass
class InsiderData:
    purchases: list[Purchase] = field(default_factory=list)
    history: TradeHistory = field(default_factory=TradeHistory)
    rows_by_accession: dict[str, list[TransactionRow]] = field(default_factory=dict)
    stats: dict = field(default_factory=lambda: defaultdict(int))
    quarters_loaded: list[str] = field(default_factory=list)
    quarters_missing: list[str] = field(default_factory=list)


def _label(yq: tuple[int, int]) -> str:
    return f"{yq[0]}q{yq[1]}"


def parse_quarter(text: str) -> tuple[int, int]:
    t = text.strip().lower()
    if len(t) != 6 or t[4] != "q" or t[5] not in "1234" or not t[:4].isdigit():
        raise argparse.ArgumentTypeError(f"quarter must look like 2024q1, not {text!r}")
    return int(t[:4]), int(t[5])


def registered_quarters() -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(pass-1 quarters, history quarters) of the registered design."""
    return (datasets.quarters_between(LOOKBACK_QUARTER, EVENT_QUARTERS[1]),
            datasets.quarters_between(*HISTORY_QUARTERS))


def load_insider_data(
    data_dir: str, user_agent: str, *, offline: bool = False, quarters: list[tuple[int, int]] | None = None,
) -> InsiderData:
    """Two passes over the data sets: qualifying purchases, then the P/S history of those insiders.

    quarters (debug override) restricts both passes to the listed quarters. A quarter that cannot be
    obtained online stops the run; offline it is recorded as a cache miss (check_offline_misses decides).
    """
    event_qs, history_qs = registered_quarters()
    if quarters is not None:
        wanted = set(quarters)
        event_qs = [q for q in event_qs if q in wanted]
        history_qs = [q for q in history_qs if q in wanted]
    data = InsiderData()
    paths: dict[tuple[int, int], str] = {}

    def path_for(yq: tuple[int, int]) -> str | None:
        if yq not in paths:
            p = datasets.download_quarter(yq[0], yq[1], data_dir, user_agent, offline=offline)
            if p is None:
                data.quarters_missing.append(_label(yq))
                if not offline:
                    raise SystemExit(f"Insider data set {_label(yq)} unavailable; the registered study needs every quarter")
                return None
            paths[yq] = p
            data.quarters_loaded.append(_label(yq))
        return paths[yq]

    stats = data.stats
    for yq in event_qs:
        if (path := path_for(yq)) is None:
            continue
        for row in datasets.iter_quarter(path, codes=("P",)):
            stats["p_rows"] += 1
            if (reason := exclusion_reason(row)) is not None:
                stats[f"excluded_{reason}"] += 1
                continue
            if row.issuer_cik is None or row.filing_date is None:
                stats["excluded_no_issuer_or_date"] += 1
                continue
            stats["qualifying_purchases"] += 1
            data.purchases.append(Purchase(row.issuer_cik, insider_cik(row), row.filing_date, row.trans_date,
                                           row.value, row.accession))
            if EVENT_START <= row.filing_date <= EVENT_END:
                data.rows_by_accession.setdefault(row.accession, []).append(row)

    insiders = {p.insider_cik for p in data.purchases}
    for yq in history_qs:
        if (path := path_for(yq)) is None:
            continue
        for row in datasets.iter_quarter(path, codes=HISTORY_CODES):
            if row.document_type not in ("4", "5"):
                continue
            for o in row.owners:
                if o.cik in insiders:
                    data.history.add(o.cik, row.trans_date, row.filing_date)
    stats["history_trades"] = len(data.history)
    return data


# --- Events ----------------------------------------------------------------------


def build_events(
    data: InsiderData, window: tuple[date, date] = (EVENT_START, EVENT_END),
) -> dict[int, list[tuple[str, date, tuple[str, ...]]]]:
    """issuer CIK -> [(signal, filing_date, accessions)] for every signal of every issuer-day event."""
    start, end = window
    by_issuer: dict[int, list[Purchase]] = defaultdict(list)
    for p in data.purchases:
        by_issuer[p.issuer_cik].append(p)

    out: dict[int, list[tuple[str, date, tuple[str, ...]]]] = defaultdict(list)
    counts = data.stats
    for issuer, purchases in by_issuer.items():
        purchases.sort(key=lambda p: (p.filing_date, p.accession))
        days: dict[date, list[Purchase]] = defaultdict(list)
        for p in purchases:
            days[p.filing_date].append(p)
        for d in sorted(days):
            if not (start <= d <= end):
                continue
            group = days[d]
            total = sum(p.value for p in group)
            if total < MIN_VALUE:
                counts["below_min_value_days"] += 1
                continue

            def accs(ps: list[Purchase]) -> tuple[str, ...]:
                return tuple(sorted({p.accession for p in ps}))

            out[issuer].append((PURCHASE, d, accs(group)))
            lo = d - timedelta(days=CLUSTER_DAYS)
            window_insiders = {p.insider_cik for p in purchases if lo <= p.filing_date <= d}
            if len(window_insiders) >= 2:
                out[issuer].append((CLUSTER, d, accs(group)))
            by_class: dict[str, list[Purchase]] = defaultdict(list)
            for p in group:
                year = (p.trans_date or p.filing_date).year
                cls = data.history.classify(p.insider_cik, year, d)
                by_class[cls or "unclassified"].append(p)
            for cls, signal in _CLASS_SIGNAL.items():
                ps = by_class.get(cls, [])
                if ps and sum(p.value for p in ps) >= MIN_VALUE:
                    out[issuer].append((signal, d, accs(ps)))
    for evs in out.values():
        for sig, _, _ in evs:
            counts[f"events_{sig}"] += 1
    return dict(out)


@dataclass
class KeptEvent:
    cik: int
    ticker: str
    bucket: str
    filing_date: date
    accessions: tuple[str, ...]


def make_event_source(events_by_issuer: dict[int, list[tuple[str, date, tuple[str, ...]]]], kept: list[KeptEvent]):
    """An eventstudy event_source over precomputed insider events.

    The company check mirrors eventstudy.company_events (operating, not SIC 6770, has a ticker) from the
    same cached submissions JSON. kept collects every insider_purchase event of kept companies (cross-check).
    """

    def source(cik, bucket, user_agent, cache_dir=None, *, window=None, offline=False):
        start, end = window or (EVENT_START, EVENT_END)
        cache = os.path.join(cache_dir, f"{cik}.json") if cache_dir else None
        sub = get_json(SUBMISSIONS_URL.format(cik=cik), user_agent, cache, offline)
        if sub is None:
            if offline and not (cache and os.path.exists(cache)):
                return None, [], OFFLINE_MISS
            return None, [], "no_submissions"
        if sub.get("entityType") != "operating" or str(sub.get("sic")) in EXCLUDED_SIC:
            return None, [], "not_operating_company"
        tickers = sub.get("tickers") or []
        if not tickers:
            return None, [], "no_ticker"
        ticker = tickers[0].upper()
        events = []
        for signal, d, accessions in events_by_issuer.get(cik, []):
            if not (start <= d <= end):
                continue
            events.append(Event(cik, ticker, bucket, signal, day0_datetime(d)))
            if signal == PURCHASE:
                kept.append(KeptEvent(cik, ticker, bucket, d, accessions))
        return ticker, events, "ok"

    return source


# --- Significance and comparisons --------------------------------------------------


def t_critical(n_tests: int) -> float:
    return statistics.NormalDist().inv_cdf(1 - 0.05 / (2 * max(n_tests, 1)))


def apply_significance(study: dict) -> None:
    """Pre-registered rule: clustered t vs zero AND Welch t vs baseline, both >= the study's Bonferroni
    t_crit, positive mean and excess, positive net. Keeps summarize()'s verdict as significant_unclustered."""
    t_crit = t_critical(study["testing"]["n_tests"])
    for r in study["results"]:
        r["significant_unclustered"] = r["significant"]
        excess = r["excess_vs_baseline"]
        r["significant"] = bool(
            abs(r["t_stat_clustered"]) >= t_crit
            and r["t_vs_baseline"] is not None and abs(r["t_vs_baseline"]) >= t_crit
            and r["mean_abnormal"] > 0 and excess is not None and excess > 0
            and r["mean_net"] > 0
        )
    study["testing"]["significance_rule"] = (
        "Bonferroni over this study's cells; |t_stat_clustered| >= t_critical (firm-clustered CR1) and "
        "|t_vs_baseline| >= t_critical, mean and excess > 0, mean_net > 0 (PREREGISTRATION.md section 6). "
        "significant_unclustered is the main study's rule, reporting only."
    )


def opportunistic_vs_routine(results: list[dict]) -> list[dict]:
    """Descriptive difference (pre-registered expectation: opportunistic > routine). Not a test."""
    rows = {(r["signal"], r["bucket"], r["horizon_days"]): r for r in results}
    out = []
    for (signal, bucket, h), opp in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][2])):
        if signal != OPPORTUNISTIC_SIGNAL or (rout := rows.get((ROUTINE_SIGNAL, bucket, h))) is None:
            continue
        out.append({
            "bucket": bucket,
            "horizon_days": h,
            "n_opportunistic": opp["n"],
            "n_routine": rout["n"],
            "mean_abnormal_opportunistic": opp["mean_abnormal"],
            "mean_abnormal_routine": rout["mean_abnormal"],
            "difference": round(opp["mean_abnormal"] - rout["mean_abnormal"], 5),
            "expected_way": opp["mean_abnormal"] > rout["mean_abnormal"],
        })
    return out


# --- Raw XML cross-check ---------------------------------------------------------


def _find_primary(block: dict, accession: str) -> str | None:
    accs = block.get("accessionNumber") or []
    docs = block.get("primaryDocument") or []
    for i, a in enumerate(accs):
        if a == accession and i < len(docs):
            return docs[i]
    return None


def primary_document(cik: int, accession: str, filing_date: date, user_agent: str, data_dir: str,
                     offline: bool = False) -> str | None:
    """primaryDocument of a filing from the submissions JSON (recent block, then the older page
    covering filing_date). Uses the same caches as the main study."""
    sub_dir = os.path.join(data_dir, "submissions")
    sub = get_json(SUBMISSIONS_URL.format(cik=cik), user_agent, os.path.join(sub_dir, f"{cik}.json"), offline)
    if not sub:
        return None
    if doc := _find_primary(sub.get("filings", {}).get("recent", {}), accession):
        return doc
    for f in sub.get("filings", {}).get("files", []):
        if f.get("filingFrom", "") <= filing_date.isoformat() <= f.get("filingTo", "9999"):
            cache = os.path.join(sub_dir, "pages", f["name"])
            if not offline and not os.path.exists(cache):
                datasets.throttle()
            page = get_json(f"https://data.sec.gov/submissions/{f['name']}", user_agent, cache, offline)
            if page and (doc := _find_primary(page, accession)):
                return doc
    return None


def fetch_xml(url: str, cache_path: str, user_agent: str, offline: bool = False) -> bytes | None:
    if os.path.exists(cache_path):
        snapshot.record_read(cache_path)
        with open(cache_path, "rb") as f:
            return f.read()
    if offline:
        snapshot.record_miss(cache_path)
        return None
    for attempt in range(3):
        datasets.throttle()
        try:
            resp = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            snapshot.record_read(cache_path)
            return resp.content
        except httpx.HTTPError as exc:
            log.debug("Retry %s for %s: %s", attempt, url, exc)
    return None


def _close(a: float | None, b: float | None, abs_tol: float) -> bool:
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=1e-3, abs_tol=abs_tol)


def rows_match_xml(rows: list[TransactionRow], parsed: dict) -> bool:
    """Every dataset row has a parsed transaction with the same code and date, shares within 0.5
    (or 0.1%) and price within $0.01 (or 0.1%)."""
    txs = parsed.get("transactions", [])
    for row in rows:
        if not any(
            tx["code"] == row.code
            and tx["date"] == (row.trans_date.isoformat() if row.trans_date else None)
            and _close(tx["shares"], row.shares, 0.5)
            and _close(tx["price"], row.price, 0.01)
            for tx in txs
        ):
            return False
    return True


def crosscheck(kept: list[KeptEvent], data: InsiderData, data_dir: str, user_agent: str,
               offline: bool = False, n: int = CROSSCHECK_N, seed: int = SEED) -> dict:
    """Compare CROSSCHECK_N random events' dataset rows with the raw Form 4 XML."""
    rng = random.Random(seed)
    pool = sorted(kept, key=lambda e: (e.cik, e.filing_date))
    sample = rng.sample(pool, min(n, len(pool)))
    checked = matched = unavailable = parse_errors = 0
    mismatches = []
    for ev in sample:
        accession = rng.choice(list(ev.accessions))
        doc = primary_document(ev.cik, accession, ev.filing_date, user_agent, data_dir, offline)
        xml = None
        if doc:
            cache = os.path.join(data_dir, XML_CACHE_SUBDIR, f"{accession}.xml")
            xml = fetch_xml(raw_xml_url(ev.cik, accession, doc), cache, user_agent, offline)
        if xml is None:
            unavailable += 1
            continue
        try:
            parsed = parse_ownership_xml(xml)
        except ValueError:
            parse_errors += 1
            unavailable += 1
            continue
        checked += 1
        if rows_match_xml(data.rows_by_accession.get(accession, []), parsed):
            matched += 1
        else:
            mismatches.append(accession)
    return {
        "xml_crosscheck_n": checked,
        "match_rate": round(matched / checked, 4) if checked else None,
        "sampled": len(sample),
        "unavailable": unavailable,
        "parse_errors": parse_errors,
        "mismatched_accessions": mismatches,
        "seed": seed,
    }


# --- Run -------------------------------------------------------------------------


def caveats_extra() -> list[str]:
    return [
        "Insider study: day 0 is the first close after the Form 4 filing date (the data sets have no acceptance "
        "time), which is conservative; filings made before the close lose their same-day move.",
        "Long-only study: the borrow caveat above does not apply.",
        "Opportunistic/routine needs a trade in each of the 3 prior calendar years; insiders without that history "
        "are unclassified and only appear in the all-purchase and cluster signals.",
        "Rows come from the SEC Insider Transactions Data Sets; data_quality.match_rate reports how often a random "
        "sample of events matches the raw Form 4 XML.",
    ]


def run(
    *, offline: bool = False, data_dir: str | None = None, user_agent: str | None = None,
    quarters: list[tuple[int, int]] | None = None, design: StudyDesign = DESIGN,
) -> dict:
    """Load the data sets, build events, run the shared engine and return the results document."""
    settings = get_settings()
    data_dir = data_dir or settings.data_dir
    ua = user_agent or settings.sec_user_agent
    data = load_insider_data(data_dir, ua, offline=offline, quarters=quarters)
    events_by_issuer = build_events(data, design.window)
    kept: list[KeptEvent] = []
    study = run_design(design, make_event_source(events_by_issuer, kept), SIGNAL_DEFS,
                       offline=offline, data_dir=data_dir, user_agent=ua)
    apply_significance(study)
    study["opportunistic_vs_routine"] = opportunistic_vs_routine(study["results"])
    quality = crosscheck(kept, data, data_dir, ua, offline)
    quality["datasets"] = {
        "quarters_loaded": sorted(data.quarters_loaded),
        "quarters_missing": sorted(data.quarters_missing),
        **{k: v for k, v in sorted(data.stats.items())},
    }
    study["data_quality"] = quality
    study["preregistration"] = PREREGISTRATION
    study["preregistered_on"] = PREREGISTERED_ON
    study["config"]["insider_data"] = "SEC Insider Transactions Data Sets (Form 3/4/5), https://www.sec.gov/dera/data/form-345"
    study["config"]["min_value"] = MIN_VALUE
    study["config"]["cluster_days"] = CLUSTER_DAYS
    study["config"]["day0_rule"] = "first close after the filing date"
    if quarters is not None:
        study["config"]["quarters_override"] = [_label(q) for q in sorted(quarters)]
    study["caveats"].extend(caveats_extra())
    return study


def _guard_output(path: str) -> None:
    if os.path.basename(path) == RESULTS_FILE:
        raise SystemExit(f"Refusing to write the insider study to {RESULTS_FILE}: that file is the live evidence")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_replay_args(parser)
    parser.add_argument("--quarters", nargs="+", type=parse_quarter, default=None,
                        help="debug only: load just these quarters (e.g. 2024q1 2024q2); not the registered study")
    args = parser.parse_args(argv)
    data_dir = get_settings().data_dir
    path = args.output or os.path.join(data_dir, DESIGN.results_file)
    _guard_output(path)
    snapshot.start_tracking()
    try:
        study = run(offline=args.offline, data_dir=data_dir, quarters=args.quarters, design=DESIGN)
        check_offline_misses(args.allow_missing)
        if args.offline:
            study["offline_misses"] = len(snapshot.misses())
        manifest = write_study(study, path, data_dir)
    finally:
        snapshot.stop_tracking()
    q = study["data_quality"]
    log.info("Wrote %s (manifest %s): %d events, %d results, XML match %s of %d", path, manifest,
             study["measured_events"], len(study["results"]), q["match_rate"], q["xml_crosscheck_n"])
    log_highlights(study)


if __name__ == "__main__":
    main()
