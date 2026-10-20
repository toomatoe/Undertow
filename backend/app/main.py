import asyncio
import json
import logging
import os
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.orm import Session

from app import health as health_mod
from app.backtest import borrow
from app.backtest.report import is_search, read_runs, trial_id
from app.config import AdminSettings, get_settings
from app.db import SessionLocal, get_session, init_db
from app.alerts import service as alerts
from app.alerts.service import Alerter
from app.delivery import service as delivery
from app.delivery.routes import router as delivery_router
from app.delivery.settings import get_delivery_settings
from app.fundamentals import service as fundamentals
from app.journal import digest as chain
from app.journal import service as journal
from app.paper import service as paper
from app.newsletter import service as newsletter
from app.models import AlertLog, Article, ArticleTicker, Company, IngestRun, JournalEntry, TradingHalt, WatchlistItem
from app.sources import halts as halts_source
from app.pipeline.companies import BUCKET_NAMES, load_latest_floats, sync_companies
from app.pipeline.enrich import Enricher
from app.pipeline.events import broadcaster
from app.pipeline.ingest import NEW_ARTICLE_HOOKS, backfill_signals, build_sources, poll_edgar, run_ingest
from app.insiders import evidence as insider_evidence
from app.pipeline.signals import ALL_SIGNALS, FORWARD_TEST_SIGNALS, is_forward_test, signal_def, signal_dict
from app.pipeline.tickers import TickerUniverse
from app.research.eventstudy import RESULTS_FILE
from app.research.oos import OOS_RESULTS_FILE
from app.research_jobs import MODULES, JobBusy, ResearchJobs
from app.schemas import (
    AdminStatus,
    ArticleOut,
    ArticlePage,
    ChainDay,
    ChainVerify,
    DailySentiment,
    Evidence,
    EvidenceOut,
    HealthDetails,
    HealthHistory,
    JournalChain,
    PaperPortfolioOut,
    ResearchJob,
    ResearchJobsOut,
    SignalOut,
    SourceStatus,
    Status,
    StudyInfo,
    TickerDetail,
    TrendingTicker,
)
from app.security import RateLimiter, RateLimitMiddleware, admin_dependency, admin_policy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("afterfile")
settings = get_settings()

EVIDENCE_HORIZON = 20  # trading days shown next to live alerts
# Fixed allowlist: study name -> result file under DATA_DIR. Paths are never built from user input.
STUDY_FILES = {
    "main": RESULTS_FILE,
    "oos": OOS_RESULTS_FILE,
    "insider_purchases": "event_study_insider_purchases.json",
}
StudyName = Literal["main", "oos", "insider_purchases"]
CHAIN_TAIL = 30  # lines returned by GET /api/journal/chain
VERIFY_TTL_SECONDS = 600  # verify_chain recomputes every sealed day: cache it
PAPER_TTL_SECONDS = 600  # paper portfolio: recomputed from the journal + cached prices at most every 10 minutes
PAPER_NOTIONAL = 10_000  # fixed server-side (hypothetical notional per position)


class AppState:
    universe = TickerUniverse()
    enricher: Enricher | None = None
    sizes: dict[str, str | None] = {}  # symbol -> size bucket
    study: dict | None = None
    evidence: dict[tuple[str, str], Evidence] = {}  # (signal, bucket) -> result
    # Forward-test evidence ((signal, bucket) -> row of the separate pre-registered study); None = not loaded yet
    forward_evidence: dict[tuple[str, str], EvidenceOut] | None = None
    journal_marked: date | None = None
    alerter: Alerter | None = None
    # Loop heartbeats (UTC, last success) for /api/health/details
    last_slow_cycle: datetime | None = None
    last_edgar_poll: datetime | None = None
    last_halts_poll: datetime | None = None
    sealed_through: date | None = None
    last_digest_day: date | None = None
    last_purge_day: date | None = None  # UTC day of the last pending-subscriber purge
    verify_cache: tuple[float, dict] | None = None  # (monotonic time, verify_chain result)
    study_cache: dict[str, tuple[float, dict]] = {}  # study name -> (file mtime, parsed JSON)
    # (ET date, hedge, max_concurrent) -> (monotonic time, build_portfolio result): hypothetical paper portfolio
    paper_cache: dict[tuple[date, bool, int], tuple[float, dict]] = {}


state = AppState()
research_jobs: ResearchJobs | None = None


def get_research_jobs() -> ResearchJobs:
    global research_jobs
    if research_jobs is None:
        research_jobs = ResearchJobs(settings.data_dir, on_study_success=load_study)
    return research_jobs


def load_study() -> None:
    path = os.path.join(settings.data_dir, RESULTS_FILE)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        study = json.load(f)
    evidence = {
        (r["signal"], r["bucket"]): Evidence(**{k: r[k] for k in Evidence.model_fields if k in r})
        for r in study["results"]
        if r["horizon_days"] == EVIDENCE_HORIZON
    }
    state.study, state.evidence = study, evidence
    log.info("Loaded event study: %d results", len(state.study["results"]))


def load_forward_evidence() -> dict[tuple[str, str], EvidenceOut]:
    """Evidence for FORWARD_TEST_SIGNALS: the insider study's micro / 5-day row of insider_cluster_purchase, from
    {data_dir}/event_study_insider_purchases.json or the frozen bundled row (insiders/evidence.py). Never from
    event_study.json."""
    row, origin = insider_evidence.load_forward_test_row(settings.data_dir)
    out: dict[tuple[str, str], EvidenceOut] = {}
    if row is not None:
        try:
            ev = EvidenceOut(**{k: row[k] for k in EvidenceOut.model_fields if k in row},
                             study=insider_evidence.STUDY, forward_test=True)
            out[(ev.signal, ev.bucket)] = ev
        except Exception as exc:  # a malformed row must never break the article feed
            log.warning("Forward-test evidence row invalid (%s): %s", origin, exc)
    state.forward_evidence = out
    return out


def forward_evidence() -> dict[tuple[str, str], EvidenceOut]:
    return state.forward_evidence if state.forward_evidence is not None else load_forward_evidence()


def to_out(article: Article) -> ArticleOut:
    out = ArticleOut.model_validate(article)
    buckets = []
    for t in out.tickers:
        t.size_bucket = state.sizes.get(t.symbol)
        if t.size_bucket:
            buckets.append(t.size_bucket)
    for sig in out.signals:
        forward = is_forward_test(sig.code)
        out.forward_test = out.forward_test or forward
        source = forward_evidence() if forward else state.evidence
        for bucket in dict.fromkeys(buckets):
            if (ev := source.get((sig.code, bucket))) is not None:
                out.evidence.append(ev if isinstance(ev, EvidenceOut) else EvidenceOut(**ev.model_dump()))
    return out


async def ingest_once() -> dict:
    return await asyncio.to_thread(run_ingest, settings, state.universe, state.enricher)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def scheduler() -> None:
    if not settings.ingest_on_startup:
        await asyncio.sleep(settings.ingest_interval_seconds)
    while True:
        try:
            await ingest_once()
        except Exception:
            log.exception("Ingest cycle crashed")
        try:  # daily IBKR borrow snapshot: builds the borrow history the backtest lacks
            await asyncio.to_thread(borrow.snapshot, settings.data_dir)
        except Exception as exc:
            log.warning("Borrow snapshot failed: %s", exc)
        try:
            await asyncio.to_thread(journal_cycle)
        except Exception:
            log.exception("Journal cycle failed")
        try:  # tamper-evident seal of the journal through yesterday (UTC), once per day
            await asyncio.to_thread(seal_cycle)
        except Exception:
            log.exception("Journal seal failed")
        try:  # weekly newsletter: build last week's issue once, after the week is complete (emails it if configured)
            await asyncio.to_thread(newsletter_cycle)
        except Exception:
            log.exception("Newsletter build failed")
        try:  # daily email digest of yesterday (ET), once the configured ET hour has passed
            await asyncio.to_thread(digest_cycle)
        except Exception:
            log.exception("Daily digest failed")
        try:  # delete never-confirmed sign-ups older than 30 days, once per UTC day
            await asyncio.to_thread(purge_cycle)
        except Exception:
            log.exception("Pending subscriber purge failed")
        state.last_slow_cycle = utcnow()
        try:  # uptime history for /api/health/history
            await asyncio.to_thread(uptime_cycle)
        except Exception as exc:
            log.warning("Uptime snapshot failed: %s", exc)
        await asyncio.sleep(settings.ingest_interval_seconds)


async def edgar_poller() -> None:
    """Fast loop: poll EDGAR every edgar_poll_seconds so alerts go out within seconds of a filing."""
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(poll_edgar, settings, state.universe)
            state.last_edgar_poll = utcnow()
        except Exception:
            log.exception("EDGAR poll crashed")
        try:
            await asyncio.to_thread(poll_halts)
            state.last_halts_poll = utcnow()
        except Exception as exc:
            log.warning("Halt poll failed: %s", exc)
        await asyncio.sleep(settings.edgar_poll_seconds)


def poll_halts() -> None:
    with SessionLocal() as session:
        res = alerts.store_halts(session, halts_source.fetch(), settings)
        if res["new"]:
            log.info("Halts: %s", res)


def evidence_for(article: Article) -> list[dict]:
    return [e.model_dump() for e in to_out(article).evidence]


def journal_cycle() -> None:
    """Record new signals every cycle; mark prices at most once per day."""
    with SessionLocal() as session:
        if n := journal.record_new(session, settings.data_dir):
            log.info("Journal: recorded %d new signal(s)", n)
        today = datetime.now(timezone.utc).date()
        if state.journal_marked != today:
            log.info("Journal marked: %s", journal.mark(session, settings.data_dir))
            state.journal_marked = today


def newsletter_kwargs() -> dict:
    return {"user_agent": settings.sec_user_agent, "public_base_url": settings.public_base_url}


def newsletter_cycle() -> None:
    """Build the issue for the most recently completed week (ending Sunday) if it doesn't exist yet.
    A NEW issue is emailed to confirmed subscribers when delivery is configured (blocking: runs in a thread)."""
    with SessionLocal() as session:
        if built := newsletter.ensure_latest(session, settings.data_dir, **newsletter_kwargs()):
            log.info("Newsletter: built issue %s", built)
            if get_delivery_settings().enabled:
                try:
                    log.info("Newsletter email: %s", delivery.send_newsletter(session, settings.data_dir, built))
                except Exception:
                    log.exception("Newsletter email failed")


def digest_cycle(now: datetime | None = None) -> None:
    """Daily digest for YESTERDAY (ET), once per ET day after EMAIL_DAILY_DIGEST_HOUR_ET. Idempotent per subscriber."""
    if not get_delivery_settings().enabled:
        return
    day = delivery.daily_digest_day(now)
    if day is None or state.last_digest_day == day:
        return
    with SessionLocal() as session:
        try:
            log.info("Daily digest: %s", delivery.send_daily_digest(session, settings.data_dir, day))
            state.last_digest_day = day
        except Exception:
            log.exception("Daily digest email failed")


def purge_cycle(now: datetime | None = None) -> None:
    """Delete never-confirmed sign-ups (delivery.purge_pending) at most once per UTC day. Runs even when delivery is
    off now, so pending rows from an earlier configuration still expire. A failed purge is retried next cycle."""
    now = now or utcnow()
    today = now.astimezone(timezone.utc).date()
    if state.last_purge_day == today:
        return
    with SessionLocal() as session:
        if n := delivery.purge_pending(session, now=now):
            log.info("Delivery: purged %d unconfirmed sign-up(s)", n)
    state.last_purge_day = today


def seal_cycle(now: datetime | None = None) -> None:
    """Seal the journal hash chain through yesterday (UTC). seal_through is idempotent; this skips the file read
    once the day is done."""
    now = now or utcnow()
    yesterday = now.astimezone(timezone.utc).date() - timedelta(days=1)
    if state.sealed_through == yesterday:
        return
    with SessionLocal() as session:
        added = chain.seal_through(session, settings.data_dir, yesterday, now=now)
    if added:
        log.info("Journal chain: sealed %d day(s) through %s", len(added), added[-1]["day"])
        state.verify_cache = None
    state.sealed_through = yesterday


def health_inputs() -> health_mod.HealthInputs:
    db_ok, db_error = True, None
    last_ingest = alert_last = None
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            last_ingest = session.scalar(select(func.max(IngestRun.started_at)).where(IngestRun.error.is_(None)))
            row = session.scalars(select(AlertLog).where(AlertLog.status != "skipped").order_by(AlertLog.id.desc()).limit(1)).first()
            if row is not None:
                at = row.detected_at if row.detected_at.tzinfo else row.detected_at.replace(tzinfo=timezone.utc)
                alert_last = {"status": row.status, "reason": row.reason, "at": at.isoformat()}
    except Exception as exc:  # health must report, never raise
        db_ok, db_error = False, type(exc).__name__
    try:
        issues = newsletter.list_issues(settings.data_dir)
    except OSError:
        issues = []
    try:  # never creates the manager here (lifespan does)
        active = (research_jobs.snapshot().get("active") or {}).get("kind") if research_jobs else None
    except Exception:
        active = None
    return health_mod.HealthInputs(
        db_ok=db_ok, db_error=db_error, last_ingest_ok=last_ingest,
        last_edgar_poll=state.last_edgar_poll, last_halts_poll=state.last_halts_poll,
        edgar_poll_seconds=settings.edgar_poll_seconds, ingest_interval_seconds=settings.ingest_interval_seconds,
        journal_marked=state.journal_marked,
        newsletter_latest={"id": issues[0]["id"], "week_end": issues[0].get("week_end")} if issues else None,
        alerts_channel=state.alerter.channel if state.alerter else "none", alerts_last=alert_last,
        email_enabled=get_delivery_settings().enabled, research_active=active,
    )


def uptime_cycle() -> None:
    health_mod.append_snapshot(settings.data_dir, health_mod.evaluate(health_inputs()))


def load_companies() -> None:
    floats = load_latest_floats(settings.data_dir, settings.sec_user_agent, datetime.now(timezone.utc).year)
    count = sync_companies(state.universe, floats)
    with SessionLocal() as session:
        state.sizes = dict(session.execute(select(Company.symbol, Company.size_bucket)).all())
    sized = sum(1 for b in state.sizes.values() if b)
    log.info("Companies: %d symbols, %d with public float", count, sized)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_research_jobs()
    init_db()
    broadcaster.bind_loop(asyncio.get_running_loop())
    state.universe = await asyncio.to_thread(TickerUniverse.load, settings.data_dir, settings.sec_user_agent)
    log.info("Ticker universe: %d symbols", len(state.universe))
    await asyncio.to_thread(load_companies)
    with SessionLocal() as session:
        if n := backfill_signals(session):
            log.info("Backfilled signals on %d filings", n)
    load_study()
    load_forward_evidence()
    if settings.enrich_enabled:
        state.enricher = Enricher(settings.anthropic_api_key, settings.enrich_model)
        log.info("LLM enrichment on (%s)", settings.enrich_model)
    state.alerter = Alerter(settings, evidence_for)
    if state.alerter not in NEW_ARTICLE_HOOKS:
        NEW_ARTICLE_HOOKS.append(state.alerter)
    log.info("Alerts: channel=%s, min severity %d, sizes %s", state.alerter.channel, settings.alert_min_severity, settings.alert_sizes)
    tasks = [asyncio.create_task(scheduler())]
    if settings.edgar_poll_seconds > 0:
        tasks.append(asyncio.create_task(edgar_poller()))
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.to_thread(get_research_jobs().shutdown)


app = FastAPI(title="Afterfile API", version="0.2.0", lifespan=lifespan)
# Per-client rate limits (app/security.py). The middleware looks the limiter up per request, so tests can swap it.
rate_limiter: RateLimiter | None = RateLimiter(
    settings.rate_limit_per_minute, settings.rate_limit_write_per_minute, trust_proxy=settings.trust_proxy_headers
)
app.add_middleware(RateLimitMiddleware, get_limiter=lambda: rate_limiter)
# Added last = outermost, so 429 responses carry CORS headers too.
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)
app.include_router(delivery_router)  # /api/subscribe, /api/unsubscribe, ... (app/delivery/AGENTS.md)

SentimentFilter = Literal["positive", "negative", "neutral"]

# One admin policy for every mutating endpoint (app/security.py). `research_launch` is the policy's settings
# object: the global Settings (which inherits AdminSettings); tests replace it with an AdminSettings instance.
ResearchLaunchSettings = AdminSettings  # backwards-compatible name
research_launch: AdminSettings = settings


def current_admin_policy(scope: str = "mutations"):
    return admin_policy(research_launch, settings.public_base_url, scope)


def research_launch_policy() -> tuple[bool, str | None]:
    """(enabled, admin token or None) for research launches."""
    p = current_admin_policy("research")
    return p.enabled, p.token


require_admin = admin_dependency(current_admin_policy)
require_research_launch = require_admin("research")


@app.get("/api/research/jobs", response_model=ResearchJobsOut)
async def research_job_status():
    enabled, token = research_launch_policy()
    return {**get_research_jobs().snapshot(), "enabled": enabled, "requires_token": token is not None}


@app.post("/api/research/jobs/{kind}", response_model=ResearchJob, status_code=202,
          dependencies=[Depends(require_research_launch)])
async def start_research_job(kind: str = Path(max_length=64)):
    if kind not in MODULES:  # fixed allowlist; clients choose a kind, never a command
        raise HTTPException(422, f"Unknown research kind. Use one of: {', '.join(MODULES)}")
    try:
        return get_research_jobs().start(kind)
    except JobBusy as exc:
        raise HTTPException(409, str(exc)) from exc


def parse_sizes(size: str | None) -> list[str]:
    if not size or size == "all":
        return []
    sizes = [s.strip() for s in size.split(",") if s.strip()]
    bad = [s for s in sizes if s not in BUCKET_NAMES]
    if bad:
        raise HTTPException(422, f"Unknown size bucket(s): {bad}. Use {BUCKET_NAMES}")
    return sizes


def apply_common_filters(stmt, *, ticker, sizes, watchlist, signal, min_severity, source=None):
    if ticker:
        stmt = stmt.where(Article.tickers.any(ArticleTicker.symbol == ticker.upper()))
    if sizes:
        sized = select(Company.symbol).where(Company.size_bucket.in_(sizes))
        stmt = stmt.where(Article.tickers.any(ArticleTicker.symbol.in_(sized)))
    if watchlist:
        stmt = stmt.where(Article.tickers.any(ArticleTicker.symbol.in_(select(WatchlistItem.symbol))))
    if signal:
        # JSON arrays are stored as text in both SQLite and Postgres JSON columns
        stmt = stmt.where(cast(Article.signals, String).like(f'%"{signal}"%'))
    if min_severity:
        stmt = stmt.where(Article.severity >= min_severity)
    if source:
        stmt = stmt.where(Article.source == source)
    return stmt


@app.get("/api/health")
def health():
    """Cheap liveness check (no DB). Exempt from rate limits; used by the container healthcheck."""
    return {"ok": True}


@app.get("/api/health/details", response_model=HealthDetails)
def health_details():
    """Per-component state with the thresholds in app/health.py (db failure = down; stale ingest/EDGAR = degraded)."""
    return health_mod.evaluate(health_inputs())


@app.get("/api/health/history", response_model=HealthHistory)
def health_history(days: int = Query(7, ge=1, le=health_mod.UPTIME_KEEP_DAYS)):
    """Uptime % per component and per day, plus status transitions, from {data_dir}/uptime.jsonl."""
    return health_mod.history(health_mod.read_snapshots(settings.data_dir), days)


@app.get("/api/articles", response_model=ArticlePage)
def list_articles(
    q: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
    sentiment: SentimentFilter | None = None,
    event_type: str | None = None,
    size: str | None = Query(None, description="Comma-separated size buckets, e.g. nano,micro,small"),
    watchlist: bool = False,
    signal: str | None = None,
    min_severity: int | None = Query(None, ge=1, le=3),
    min_relevance: float | None = Query(None, ge=0, le=1),
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(Article)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Article.title.ilike(like), Article.snippet.ilike(like), Article.ai_summary.ilike(like)))
    stmt = apply_common_filters(
        stmt, ticker=ticker, sizes=parse_sizes(size), watchlist=watchlist, signal=signal,
        min_severity=min_severity, source=source,
    )
    if sentiment:
        stmt = stmt.where(Article.sentiment_label == sentiment)
    if event_type:
        stmt = stmt.where(Article.event_type == event_type)
    if min_relevance is not None:
        stmt = stmt.where(Article.relevance >= min_relevance)
    if before:
        stmt = stmt.where(Article.published_at < before)
    rows = session.scalars(stmt.order_by(Article.published_at.desc(), Article.id.desc()).limit(limit)).all()
    items = [to_out(a) for a in rows]
    return ArticlePage(items=items, next_before=items[-1].published_at if len(items) == limit else None)


@app.get("/api/articles/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, session: Session = Depends(get_session)):
    article = session.get(Article, article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    return to_out(article)


@app.get("/api/signals", response_model=ArticlePage)
def list_signals(
    size: str | None = Query("nano,micro,small", description="Comma-separated size buckets; empty for all"),
    min_severity: int = Query(1, ge=1, le=3),
    signal: str | None = None,
    watchlist: bool = False,
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """SEC filings that carry a signal, newest first. Defaults to companies under $2B float."""
    stmt = select(Article).where(Article.severity.is_not(None))
    stmt = apply_common_filters(
        stmt, ticker=None, sizes=parse_sizes(size), watchlist=watchlist, signal=signal, min_severity=min_severity
    )
    if before:
        stmt = stmt.where(Article.published_at < before)
    rows = session.scalars(stmt.order_by(Article.published_at.desc(), Article.id.desc()).limit(limit)).all()
    items = [to_out(a) for a in rows]
    return ArticlePage(items=items, next_before=items[-1].published_at if len(items) == limit else None)


@app.get("/api/signals/catalog", response_model=list[SignalOut])
def signal_catalog():
    """Main-study signals, then the forward-test signals (forward_test: true; not part of the main study)."""
    main = sorted(ALL_SIGNALS.values(), key=lambda s: (-s.severity, s.label))
    forward = sorted(FORWARD_TEST_SIGNALS.values(), key=lambda s: (-s.severity, s.label))
    return [signal_dict(s) for s in [*main, *forward]]


STUDY_MISSING = {
    "main": "No event study yet. Run: python -m app.research.eventstudy",
    "oos": "No out-of-sample study yet. Run: python -m app.research.oos",
    "insider_purchases": "No insider-purchase study yet. Run: python -m app.insiders.study",
}


def read_study_file(name: str) -> dict | None:
    """Parsed result file for an allowlisted study name (cached by mtime), or None when missing/unreadable."""
    path = os.path.join(settings.data_dir, STUDY_FILES[name])  # KeyError for anything off the allowlist
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        state.study_cache.pop(name, None)
        return None
    cached = state.study_cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("Study %s unreadable: %s", name, exc)
        return None
    if not isinstance(data, dict):
        return None
    state.study_cache[name] = (mtime, data)
    return data


@app.get("/api/research/studies", response_model=list[StudyInfo])
def research_studies():
    """Every allowlisted study: whether its result file exists, when it was generated and how many tests it ran."""
    out = []
    for name in STUDY_FILES:
        data = read_study_file(name)
        testing = (data or {}).get("testing") or {}
        config = (data or {}).get("config") or {}
        out.append(StudyInfo(study=name, available=data is not None, generated_at=(data or {}).get("generated_at"),
                             n_tests=testing.get("n_tests") if isinstance(testing, dict) else None,
                             design=config.get("study") if isinstance(config, dict) else None))
    return out


@app.get("/api/research/event-study")
def event_study(study: StudyName = "main"):
    """Event-study results. study=main (default, the live evidence; response unchanged) | oos | insider_purchases."""
    if study != "main":
        data = read_study_file(study)
        if data is None:
            raise HTTPException(404, STUDY_MISSING[study])
        return data
    if state.study is None:
        load_study()
    if state.study is None:
        raise HTTPException(404, STUDY_MISSING["main"])
    return state.study


@app.get("/api/alerts")
def alerts_status(limit: int = Query(50, ge=1, le=500), session: Session = Depends(get_session)):
    """Alert configuration, delivery log and detection latency (EDGAR acceptance -> detected)."""
    rows = session.execute(
        select(AlertLog, Article.title, Article.url).join(Article, Article.id == AlertLog.article_id)
        .order_by(AlertLog.id.desc()).limit(limit)
    ).all()
    return {
        "channel": state.alerter.channel if state.alerter else "none",
        "min_severity": settings.alert_min_severity,
        "sizes": settings.alert_sizes,
        "poll_seconds": settings.edgar_poll_seconds,
        **alerts.stats(session),
        "log": [
            {"article_id": a.article_id, "title": t, "url": u, "status": a.status, "reason": a.reason,
             "detected_at": a.detected_at.isoformat(), "latency_seconds": a.latency_seconds}
            for a, t, u in rows
        ],
    }


@app.post("/api/alerts/test", dependencies=[Depends(require_admin("mutations"))])
def alerts_test():
    if state.alerter is None:
        raise HTTPException(503, "Alerter not started")
    return state.alerter.send_test()


@app.get("/api/halts")
def list_halts(
    symbol: str | None = None,
    size: str | None = None,
    hours: int = Query(72, ge=1, le=24 * 365),
    limit: int = Query(200, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    """Recent trading halts, newest first, with plain-English reasons and company size."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = select(TradingHalt).where(TradingHalt.halted_at >= since)
    if symbol:
        stmt = stmt.where(TradingHalt.symbol == symbol.upper())
    if sizes := parse_sizes(size):
        stmt = stmt.where(TradingHalt.symbol.in_(select(Company.symbol).where(Company.size_bucket.in_(sizes))))
    rows = session.scalars(stmt.order_by(TradingHalt.halted_at.desc()).limit(limit)).all()
    aware = lambda d: (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat() if d else None  # noqa: E731
    return [
        {"symbol": h.symbol, "name": h.name, "market": h.market, "reason_code": h.reason_code,
         "reason": halts_source.REASONS.get(h.reason_code, h.reason_code), "serious": h.reason_code in halts_source.SERIOUS,
         "halted_at": aware(h.halted_at), "resumed_at": aware(h.resumed_at), "size_bucket": state.sizes.get(h.symbol)}
        for h in rows
    ]


@app.get("/api/journal")
def journal_entries(
    signal: str | None = None,
    size: str | None = None,
    status: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    """Forward track record: every signal as recorded when it was filed, newest first."""
    stmt = select(JournalEntry, Article.title, Article.url).join(Article, Article.id == JournalEntry.article_id)
    if signal:
        stmt = stmt.where(JournalEntry.primary_signal == signal)
    if sizes := parse_sizes(size):
        stmt = stmt.where(JournalEntry.size_bucket.in_(sizes))
    if status:
        stmt = stmt.where(JournalEntry.status == status)
    rows = session.execute(stmt.order_by(JournalEntry.filed_at.desc()).limit(limit)).all()
    out = []
    for e, title, url in rows:
        d = {c.name: getattr(e, c.name) for c in JournalEntry.__table__.columns}
        d["filed_at"] = (e.filed_at if e.filed_at.tzinfo else e.filed_at.replace(tzinfo=timezone.utc)).isoformat()
        sig = signal_def(e.primary_signal)
        d.update(title=title, filing_url=url, signal_label=sig.label if sig else e.primary_signal,
                 evaluation_horizon=journal.evaluation_horizon(e.primary_signal),
                 forward_test_label=journal.forward_test_label(e.primary_signal))
        out.append(d)
    total = session.scalar(select(func.count(JournalEntry.id))) or 0
    first = session.scalar(select(func.min(JournalEntry.filed_at)))
    return {"total": total, "since": first.isoformat() if first else None, "entries": out}


@app.get("/api/journal/summary")
def journal_summary(session: Session = Depends(get_session)):
    expected = {}
    if state.study:
        for r in state.study["results"]:
            expected[(r["signal"], r["bucket"], r["horizon_days"])] = r
    for (sig, bucket), ev in forward_evidence().items():  # forward tests: the insider study's in-sample row
        expected[(sig, bucket, ev.horizon_days)] = ev.model_dump()
    return {"rows": journal.summary(session, expected), "marked": state.journal_marked.isoformat() if state.journal_marked else None}


@app.get("/api/journal/chain", response_model=JournalChain)
def journal_chain():
    """Tamper-evident seal: chain head plus the last 30 sealed days (journal/AGENTS.md)."""
    records, err = chain._read(settings.data_dir)
    head = None
    if records and not err:
        head = {"head_hash": records[-1]["hash"], "head_day": records[-1]["day"], "days": len(records)}
    return {"head": head, "lines": records[-CHAIN_TAIL:], "error": err}


@app.get("/api/journal/chain/{day}", response_model=ChainDay)
def journal_chain_day(day: str = Path(pattern=r"^\d{4}-\d{2}-\d{2}$"), session: Session = Depends(get_session)):
    """Everything needed to recompute one sealed day's hash by hand."""
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(422, "day must be a valid YYYY-MM-DD date") from None
    out = chain.export_day(session, settings.data_dir, parsed)
    if out is None:
        raise HTTPException(404, f"{day} is not sealed")
    return out


verify_lock = threading.Lock()


@app.get("/api/journal/verify", response_model=ChainVerify)
def journal_verify():
    """Recompute every sealed day from the DB (cached for 10 minutes, and dropped when new days are sealed)."""
    with verify_lock:  # one recomputation at a time; concurrent callers get the fresh cached result
        cached = state.verify_cache
        if cached and time.monotonic() - cached[0] < VERIFY_TTL_SECONDS:
            return cached[1]
        with SessionLocal() as session:
            result = {**chain.verify_chain(session, settings.data_dir), "checked_at": utcnow()}
        state.verify_cache = (time.monotonic(), result)
        return result


paper_lock = threading.Lock()


@app.get("/api/paper-portfolio", response_model=PaperPortfolioOut)
def paper_portfolio(hedge: bool = False, max_concurrent: int = Query(20, ge=1, le=100)):
    """Hypothetical paper portfolio simulated from the forward journal (app/paper/AGENTS.md). Read-only and public
    (rate-limited by the middleware); cache-only prices, no network; cached per (ET date, params) for 10 minutes."""
    key = (datetime.now(journal.ET).date(), hedge, max_concurrent)
    with paper_lock:
        cached = state.paper_cache.get(key)
        if cached and time.monotonic() - cached[0] < PAPER_TTL_SECONDS:
            return cached[1]
        with SessionLocal() as session:
            result = paper.build_portfolio(session, settings.data_dir, notional=PAPER_NOTIONAL,
                                           max_concurrent=max_concurrent, hedge=hedge, today=key[0])
        state.paper_cache = {k: v for k, v in state.paper_cache.items() if k[0] == key[0]}  # drop older days
        state.paper_cache[key] = (time.monotonic(), result)
        return result


@app.get("/api/newsletter/issues")
def newsletter_issues():
    """Archive of saved issues, newest first: id, week range, headline counts."""
    return newsletter.list_issues(settings.data_dir)


@app.post("/api/newsletter/preview")
def newsletter_preview(session: Session = Depends(get_session)):
    """The current week so far, built on demand and never saved."""
    issue = newsletter.preview(session, settings.data_dir, **newsletter_kwargs())
    return {**issue, "markdown": newsletter.render_markdown(issue), "html": newsletter.render_html(issue)}


@app.get("/api/newsletter/{issue_id}.html", response_class=HTMLResponse)
def newsletter_html(issue_id: str):
    page = newsletter.load_text(settings.data_dir, issue_id, "html")
    if page is None:
        raise HTTPException(404, f"No newsletter issue {issue_id}")
    return HTMLResponse(page)


@app.get("/api/newsletter/{issue_id}")
def newsletter_issue(issue_id: str):
    issue = newsletter.load_issue(settings.data_dir, issue_id)
    if issue is None:
        raise HTTPException(404, f"No newsletter issue {issue_id}")
    md = newsletter.load_text(settings.data_dir, issue_id, "md") or newsletter.render_markdown(issue)
    return {**issue, "markdown": md}


@app.get("/api/backtest/report")
def backtest_report():
    path = os.path.join(settings.data_dir, "backtests", "report_latest.json")
    if not os.path.exists(path):
        raise HTTPException(404, "No backtest yet. Run: python -m app.backtest.report")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/backtest/runs")
def backtest_runs(limit: int = Query(200, ge=1, le=5000)):
    """The run log: every simulation ever executed, newest first."""
    runs = read_runs(settings.data_dir)
    search = {trial_id(r) for r in runs if is_search(r)}
    return {
        "total": len(runs),
        "distinct_configs": len({(r["period"], r["config_key"]) for r in runs}),
        "search_trials": len(search),  # what the Deflated Sharpe counts
        "runs": runs[::-1][:limit],
    }


@app.get("/api/backtest/borrow")
def backtest_borrow():
    return borrow.status(settings.data_dir)


@app.get("/api/tickers/trending", response_model=list[TrendingTicker])
def trending(
    hours: int = Query(24, ge=1, le=24 * 30),
    size: str | None = None,
    limit: int = Query(15, ge=1, le=100),
    session: Session = Depends(get_session),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(ArticleTicker.symbol, func.count(), func.avg(Article.sentiment))
        .join(Article)
        .where(Article.published_at >= since)
    )
    if sizes := parse_sizes(size):
        stmt = stmt.where(ArticleTicker.symbol.in_(select(Company.symbol).where(Company.size_bucket.in_(sizes))))
    rows = session.execute(stmt.group_by(ArticleTicker.symbol).order_by(func.count().desc()).limit(limit)).all()
    return [
        TrendingTicker(
            symbol=sym,
            name=(c := state.universe.get(sym)) and c.name,
            mentions=n,
            avg_sentiment=round(avg, 3) if avg is not None else None,
            size_bucket=state.sizes.get(sym),
        )
        for sym, n, avg in rows
    ]


@app.get("/api/tickers/sitemap")
def ticker_sitemap(days: int = Query(180, ge=1, le=3650), session: Session = Depends(get_session)):
    """Tickers worth a public page: any company with a filing signal or article in the window, most recent first."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.execute(
        select(ArticleTicker.symbol, func.max(Article.published_at), func.count())
        .join(Article)
        .where(Article.published_at >= since)
        .group_by(ArticleTicker.symbol)
        .order_by(func.max(Article.published_at).desc())
    ).all()
    return [
        {"symbol": sym, "last_activity": (last if last.tzinfo else last.replace(tzinfo=timezone.utc)).isoformat(), "items": n,
         "size_bucket": state.sizes.get(sym)}
        for sym, last, n in rows
        if sym in state.sizes
    ]


@app.get("/api/tickers/{symbol}", response_model=TickerDetail)
def ticker_detail(symbol: str, days: int = Query(30, ge=1, le=365), session: Session = Depends(get_session)):
    symbol = symbol.upper()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    articles = session.scalars(
        select(Article)
        .where(Article.tickers.any(ArticleTicker.symbol == symbol), Article.published_at >= since)
        .order_by(Article.published_at.desc())
        .limit(200)
    ).all()
    company = session.get(Company, symbol)
    if not articles and not company:
        raise HTTPException(404, f"No data for {symbol}")

    by_day: dict[str, list[float | None]] = defaultdict(list)
    for a in articles:
        by_day[a.published_at.date().isoformat()].append(a.sentiment)
    daily = []
    for day in sorted(by_day):
        scores = [s for s in by_day[day] if s is not None]
        daily.append(DailySentiment(day=day, mentions=len(by_day[day]), avg_sentiment=round(sum(scores) / len(scores), 3) if scores else None))
    scores = [a.sentiment for a in articles if a.sentiment is not None]

    return TickerDetail(
        symbol=symbol,
        name=company.name if company else None,
        cik=company.cik if company else None,
        public_float=company.public_float if company else None,
        float_as_of=company.float_as_of if company else None,
        size_bucket=company.size_bucket if company else None,
        on_watchlist=session.get(WatchlistItem, symbol) is not None,
        mentions=len(articles),
        avg_sentiment=round(sum(scores) / len(scores), 3) if scores else None,
        daily=daily,
        articles=[to_out(a) for a in articles[:50]],
    )


@app.get("/api/tickers/{symbol}/fundamentals")
async def ticker_fundamentals(symbol: str, session: Session = Depends(get_session)):
    """Cash runway and dilution history from SEC company facts and filings (cached daily)."""
    company = session.get(Company, symbol.upper())
    if company is None:
        raise HTTPException(404, f"Unknown ticker {symbol}")
    try:
        return await asyncio.to_thread(fundamentals.company_profile, company.cik, settings.data_dir, settings.sec_user_agent, company.symbol)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"SEC data unavailable: {exc}") from exc


@app.get("/api/watchlist", response_model=list[TrendingTicker])
def get_watchlist(session: Session = Depends(get_session)):
    since = datetime.now(timezone.utc) - timedelta(days=7)
    symbols = session.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.added_at)).all()
    counts = dict(
        session.execute(
            select(ArticleTicker.symbol, func.count())
            .join(Article)
            .where(ArticleTicker.symbol.in_(symbols), Article.published_at >= since)
            .group_by(ArticleTicker.symbol)
        ).all()
    )
    return [
        TrendingTicker(
            symbol=s,
            name=(c := state.universe.get(s)) and c.name,
            mentions=counts.get(s, 0),
            avg_sentiment=None,
            size_bucket=state.sizes.get(s),
        )
        for s in symbols
    ]


@app.put("/api/watchlist/{symbol}", dependencies=[Depends(require_admin("mutations"))])
def add_to_watchlist(symbol: str, session: Session = Depends(get_session)):
    symbol = symbol.upper()
    if symbol not in state.universe and len(state.universe) > 0:
        raise HTTPException(404, f"Unknown ticker {symbol}")
    if not session.get(WatchlistItem, symbol):
        session.add(WatchlistItem(symbol=symbol))
        session.commit()
    return {"symbol": symbol, "on_watchlist": True}


@app.delete("/api/watchlist/{symbol}", dependencies=[Depends(require_admin("mutations"))])
def remove_from_watchlist(symbol: str, session: Session = Depends(get_session)):
    item = session.get(WatchlistItem, symbol.upper())
    if item:
        session.delete(item)
        session.commit()
    return {"symbol": symbol.upper(), "on_watchlist": False}


@app.get("/api/status", response_model=Status)
def status(session: Session = Depends(get_session)):
    sources = []
    for src in build_sources(settings, state.universe):
        run = session.scalars(
            select(IngestRun).where(IngestRun.source_name == src.name).order_by(IngestRun.id.desc()).limit(1)
        ).first()
        sources.append(
            SourceStatus(
                name=src.name,
                last_run=run.started_at if run else None,
                fetched=run.fetched if run else None,
                inserted=run.inserted if run else None,
                error=run.error if run else None,
            )
        )
    policy = current_admin_policy("mutations")
    return Status(
        articles=session.scalar(select(func.count(Article.id))) or 0,
        enriched=session.scalar(select(func.count(Article.id)).where(Article.enriched_at.is_not(None))) or 0,
        tickers_loaded=len(state.universe),
        alpaca_enabled=settings.alpaca_enabled,
        enrich_enabled=settings.enrich_enabled,
        enrich_model=settings.enrich_model if settings.enrich_enabled else None,
        sources=sources,
        admin=AdminStatus(protected=policy.protected, mutations_enabled=policy.enabled),
    )


@app.post("/api/ingest", dependencies=[Depends(require_admin("mutations"))])
async def trigger_ingest():
    return await ingest_once()


@app.get("/api/stream")
async def stream(request: Request):
    """Server-sent events: `article` (new) and `article_updated` (enriched)."""
    queue = broadcaster.subscribe()

    async def events():
        try:
            yield "retry: 5000\n\n"
            while not await request.is_disconnected():
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
