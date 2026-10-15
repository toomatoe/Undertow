from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator


class TickerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    method: str


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    title: str
    snippet: str | None
    source: str
    source_name: str
    author: str | None
    published_at: datetime
    ai_summary: str | None
    sentiment: float | None
    sentiment_label: str | None
    event_type: str | None
    relevance: float | None
    enrich_model: str | None
    tickers: list[TickerOut]

    @field_validator("published_at")
    @classmethod
    def assume_utc(cls, v: datetime) -> datetime:
        # SQLite drops tzinfo; everything is stored in UTC
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class ArticlePage(BaseModel):
    items: list[ArticleOut]
    next_before: datetime | None


class TrendingTicker(BaseModel):
    symbol: str
    name: str | None
    mentions: int
    avg_sentiment: float | None


class DailySentiment(BaseModel):
    day: str
    mentions: int
    avg_sentiment: float | None


class TickerDetail(BaseModel):
    symbol: str
    name: str | None
    cik: int | None
    mentions: int
    avg_sentiment: float | None
    daily: list[DailySentiment]
    articles: list[ArticleOut]


class SourceStatus(BaseModel):
    name: str
    last_run: datetime | None
    fetched: int | None
    inserted: int | None
    error: str | None


class Status(BaseModel):
    articles: int
    enriched: int
    tickers_loaded: int
    alpaca_enabled: bool
    enrich_enabled: bool
    enrich_model: str | None
    sources: list[SourceStatus]
