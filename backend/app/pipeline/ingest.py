"""One ingestion cycle: fetch every source -> dedupe -> tag tickers -> store -> enrich -> broadcast."""

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.models import Article, ArticleTicker, IngestRun
from app.pipeline.dedupe import title_hash, url_hash
from app.pipeline.enrich import Enricher
from app.pipeline.events import broadcaster
from app.pipeline.tickers import TickerUniverse, tag_tickers
from app.sources.alpaca import AlpacaNewsSource
from app.sources.base import RawArticle, Source
from app.sources.edgar import EdgarSource
from app.sources.rss import RssSource

log = logging.getLogger(__name__)

TITLE_DEDUPE_WINDOW = timedelta(days=2)
_lock = threading.Lock()  # one cycle at a time (scheduler + manual trigger)


def build_sources(settings: Settings, universe: TickerUniverse) -> list[Source]:
    sources: list[Source] = []
    if settings.alpaca_enabled:
        sources.append(AlpacaNewsSource(settings.alpaca_api_key_id, settings.alpaca_api_secret_key))
    if settings.edgar_enabled:
        sources.append(EdgarSource(settings.sec_user_agent, universe))
    for name, url in settings.rss_feeds.items():
        sources.append(RssSource(name, url, settings.sec_user_agent))
    return sources


def is_duplicate(session: Session, raw: RawArticle, uhash: str, thash: str) -> bool:
    if session.scalar(select(Article.id).where(Article.url_hash == uhash)):
        return True
    window_start = raw.published_at - TITLE_DEDUPE_WINDOW
    return bool(
        session.scalar(
            select(Article.id).where(Article.title_hash == thash, Article.published_at >= window_start).limit(1)
        )
    )


def store(session: Session, raw: RawArticle, universe: TickerUniverse) -> Article | None:
    uhash, thash = url_hash(raw.url), title_hash(raw.title)
    if is_duplicate(session, raw, uhash, thash):
        return None
    tickers = dict(sorted(raw.tickers, key=lambda t: t[1]))  # symbol -> method
    for sym, method in tag_tickers(f"{raw.title} {raw.snippet or ''}", universe):
        tickers.setdefault(sym, method)
    article = Article(
        url=raw.url,
        url_hash=uhash,
        title_hash=thash,
        title=raw.title,
        snippet=raw.snippet,
        source=raw.source,
        source_name=raw.source_name,
        author=(raw.author or None) and raw.author[:256],
        published_at=raw.published_at,
        event_type=raw.event_type,
        tickers=[ArticleTicker(symbol=s, method=m) for s, m in tickers.items()],
    )
    session.add(article)
    session.flush()
    return article


def enrich_pending(session: Session, enricher: Enricher, universe: TickerUniverse, limit: int) -> int:
    pending = session.scalars(
        select(Article).where(Article.enriched_at.is_(None)).order_by(Article.published_at.desc()).limit(limit)
    ).all()
    done = 0
    for article in pending:
        result = enricher.enrich(article.title, article.snippet, article.source_name)
        if result is None:
            continue
        article.ai_summary = result.summary
        article.sentiment = result.sentiment
        article.sentiment_label = result.sentiment_label
        article.relevance = result.relevance
        # EDGAR item mapping is authoritative; otherwise take the model's category
        article.event_type = article.event_type or result.event_type
        article.enrich_model = enricher.model
        article.enriched_at = datetime.now(timezone.utc)
        existing = {t.symbol for t in article.tickers}
        for sym in result.tickers:
            if sym not in existing and (len(universe) == 0 or sym in universe):
                article.tickers.append(ArticleTicker(symbol=sym, method="llm"))
                existing.add(sym)
        session.commit()
        broadcaster.publish("article_updated", {"id": article.id})
        done += 1
    return done


def run_ingest(settings: Settings, universe: TickerUniverse, enricher: Enricher | None) -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        stats = {"sources": {}, "inserted": 0, "enriched": 0}
        for source in build_sources(settings, universe):
            run = IngestRun(source_name=source.name, fetched=0, inserted=0)
            with SessionLocal() as session:
                try:
                    raws = source.fetch()
                    run.fetched = len(raws)
                    for raw in sorted(raws, key=lambda r: r.published_at):
                        article = store(session, raw, universe)
                        if article:
                            run.inserted += 1
                            session.commit()
                            broadcaster.publish("article", {"id": article.id})
                except Exception as exc:
                    session.rollback()
                    run.error = f"{type(exc).__name__}: {exc}"[:1000]
                    log.warning("Source %s failed: %s", source.name, run.error)
                session.add(run)
                session.commit()
            stats["sources"][source.name] = {"fetched": run.fetched, "inserted": run.inserted, "error": run.error}
            stats["inserted"] += run.inserted

        if enricher:
            with SessionLocal() as session:
                stats["enriched"] = enrich_pending(session, enricher, universe, settings.enrich_max_per_cycle)
        log.info("Ingest cycle done: %s new, %s enriched", stats["inserted"], stats["enriched"])
        return stats
    finally:
        _lock.release()
