from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class ResearchJob(BaseModel):
    id: str
    kind: Literal["backtest", "event_study"]
    status: Literal["running", "succeeded", "failed", "interrupted"]
    started_at: datetime
    finished_at: datetime | None
    message: str


class ResearchJobsOut(BaseModel):
    active: ResearchJob | None
    latest: dict[str, ResearchJob | None]


class TickerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    method: str
    size_bucket: str | None = None


class SignalOut(BaseModel):
    code: str
    label: str
    direction: str
    severity: int
    why: str


class Evidence(BaseModel):
    """Historical event-study result for one signal in one size bucket."""

    signal: str
    bucket: str
    n: int
    horizon_days: int
    mean_abnormal: float  # after-event drift vs benchmark, gross
    mean_net: float  # after assumed round-trip costs (and borrow for shorts), in the expected direction
    excess_vs_baseline: float | None = None  # drift minus the same stocks' ordinary-day drift
    t_stat: float
    significant: bool  # survives the multiple-testing correction


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
    form: str | None = None
    severity: int | None = None
    signals: list[SignalOut] = []
    ai_flags: list[str] | None = None
    evidence: list[Evidence] = []

    @field_validator("signals", mode="before")
    @classmethod
    def expand_signals(cls, v):
        from app.pipeline.signals import ALL_SIGNALS, signal_dict

        if not v:
            return []
        return [signal_dict(ALL_SIGNALS[c]) if isinstance(c, str) else c for c in v if not isinstance(c, str) or c in ALL_SIGNALS]

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
    size_bucket: str | None = None


class DailySentiment(BaseModel):
    day: str
    mentions: int
    avg_sentiment: float | None


class TickerDetail(BaseModel):
    symbol: str
    name: str | None
    cik: int | None
    public_float: int | None = None
    float_as_of: str | None = None
    size_bucket: str | None = None
    on_watchlist: bool = False
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
