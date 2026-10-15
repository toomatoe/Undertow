import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session, init_db
from app.models import Article, ArticleTicker, IngestRun
from app.pipeline.enrich import Enricher
from app.pipeline.events import broadcaster
from app.pipeline.ingest import build_sources, run_ingest
from app.pipeline.tickers import TickerUniverse
from app.schemas import (
    ArticleOut,
    ArticlePage,
    DailySentiment,
    SourceStatus,
    Status,
    TickerDetail,
    TrendingTicker,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("quantdesk")
settings = get_settings()


class AppState:
    universe = TickerUniverse()
    enricher: Enricher | None = None


state = AppState()


async def ingest_once() -> dict:
    return await asyncio.to_thread(run_ingest, settings, state.universe, state.enricher)


async def scheduler() -> None:
    if not settings.ingest_on_startup:
        await asyncio.sleep(settings.ingest_interval_seconds)
    while True:
        try:
            await ingest_once()
        except Exception:
            log.exception("Ingest cycle crashed")
        await asyncio.sleep(settings.ingest_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    broadcaster.bind_loop(asyncio.get_running_loop())
    state.universe = await asyncio.to_thread(TickerUniverse.load, settings.data_dir, settings.sec_user_agent)
    log.info("Ticker universe: %d symbols", len(state.universe))
    if settings.enrich_enabled:
        state.enricher = Enricher(settings.anthropic_api_key, settings.enrich_model)
        log.info("LLM enrichment on (%s)", settings.enrich_model)
    task = asyncio.create_task(scheduler())
    yield
    task.cancel()


app = FastAPI(title="QuantDesk API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)

SentimentFilter = Literal["positive", "negative", "neutral"]


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/articles", response_model=ArticlePage)
def list_articles(
    q: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
    sentiment: SentimentFilter | None = None,
    event_type: str | None = None,
    min_relevance: float | None = Query(None, ge=0, le=1),
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(Article)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Article.title.ilike(like), Article.snippet.ilike(like), Article.ai_summary.ilike(like)))
    if ticker:
        stmt = stmt.where(Article.tickers.any(ArticleTicker.symbol == ticker.upper()))
    if source:
        stmt = stmt.where(Article.source == source)
    if sentiment:
        stmt = stmt.where(Article.sentiment_label == sentiment)
    if event_type:
        stmt = stmt.where(Article.event_type == event_type)
    if min_relevance is not None:
        stmt = stmt.where(Article.relevance >= min_relevance)
    if before:
        stmt = stmt.where(Article.published_at < before)
    rows = session.scalars(stmt.order_by(Article.published_at.desc(), Article.id.desc()).limit(limit)).all()
    items = [ArticleOut.model_validate(a) for a in rows]
    return ArticlePage(items=items, next_before=items[-1].published_at if len(items) == limit else None)


@app.get("/api/articles/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, session: Session = Depends(get_session)):
    article = session.get(Article, article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    return article


@app.get("/api/tickers/trending", response_model=list[TrendingTicker])
def trending(hours: int = Query(24, ge=1, le=24 * 30), limit: int = Query(15, ge=1, le=100), session: Session = Depends(get_session)):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = session.execute(
        select(ArticleTicker.symbol, func.count(), func.avg(Article.sentiment))
        .join(Article)
        .where(Article.published_at >= since)
        .group_by(ArticleTicker.symbol)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [
        TrendingTicker(
            symbol=sym,
            name=(c := state.universe.get(sym)) and c.name,
            mentions=n,
            avg_sentiment=round(avg, 3) if avg is not None else None,
        )
        for sym, n, avg in rows
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
    company = state.universe.get(symbol)
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
        mentions=len(articles),
        avg_sentiment=round(sum(scores) / len(scores), 3) if scores else None,
        daily=daily,
        articles=[ArticleOut.model_validate(a) for a in articles[:50]],
    )


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
    return Status(
        articles=session.scalar(select(func.count(Article.id))) or 0,
        enriched=session.scalar(select(func.count(Article.id)).where(Article.enriched_at.is_not(None))) or 0,
        tickers_loaded=len(state.universe),
        alpaca_enabled=settings.alpaca_enabled,
        enrich_enabled=settings.enrich_enabled,
        enrich_model=settings.enrich_model if settings.enrich_enabled else None,
        sources=sources,
    )


@app.post("/api/ingest")
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
