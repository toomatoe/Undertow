from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(40), unique=True)
    title_hash: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), index=True)  # rss | edgar | alpaca
    source_name: Mapped[str] = mapped_column(String(128))
    author: Mapped[str | None] = mapped_column(String(256))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # SEC filings
    form: Mapped[str | None] = mapped_column(String(32), index=True)
    cik: Mapped[int | None] = mapped_column(Integer, index=True)
    signals: Mapped[list[str] | None] = mapped_column(JSON)  # signal codes, most severe first
    severity: Mapped[int | None] = mapped_column(Integer, index=True)  # max severity of signals
    body: Mapped[str | None] = mapped_column(Text)  # filing text (key document), for enrichment

    # LLM enrichment (null until enriched)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[float | None] = mapped_column(Float)  # -1 .. 1
    sentiment_label: Mapped[str | None] = mapped_column(String(16), index=True)
    event_type: Mapped[str | None] = mapped_column(String(32), index=True)
    relevance: Mapped[float | None] = mapped_column(Float)  # 0 .. 1, market relevance
    ai_flags: Mapped[list[str] | None] = mapped_column(JSON)  # e.g. going_concern, reverse_split
    enrich_model: Mapped[str | None] = mapped_column(String(64))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tickers: Mapped[list["ArticleTicker"]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )


class ArticleTicker(Base):
    __tablename__ = "article_tickers"

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    # How the ticker was found: vendor | cashtag | exchange | edgar | llm
    method: Mapped[str] = mapped_column(String(16))

    article: Mapped[Article] = relationship(back_populates="tickers")

    __table_args__ = (Index("ix_article_tickers_symbol", "symbol"),)


class Company(Base):
    """Ticker -> size bucket, refreshed from SEC data at startup."""

    __tablename__ = "companies"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    cik: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(256))
    public_float: Mapped[int | None] = mapped_column(BigInteger)
    float_as_of: Mapped[str | None] = mapped_column(String(10))
    size_bucket: Mapped[str | None] = mapped_column(String(8), index=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
