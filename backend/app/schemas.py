from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.research_jobs import MODULES


class ResearchJob(BaseModel):
    id: str
    kind: str  # one of research_jobs.MODULES (validated below), e.g. backtest, event_study, event_study_oos, insider_study
    status: Literal["running", "succeeded", "failed", "interrupted"]
    started_at: datetime
    finished_at: datetime | None
    message: str

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in MODULES:
            raise ValueError(f"unknown research kind {v!r}")
        return v


class ResearchJobsOut(BaseModel):
    active: ResearchJob | None
    latest: dict[str, ResearchJob | None]
    # Whether this API accepts launches at all, and whether they need an admin bearer token.
    enabled: bool = False
    requires_token: bool = False


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


class AdminStatus(BaseModel):
    """Mutation protection state (app/security.py). Never includes the token."""

    protected: bool  # an admin token is configured: mutations need a Bearer token
    mutations_enabled: bool  # ingest, alerts/test and watchlist changes are possible at all


class Status(BaseModel):
    articles: int
    enriched: int
    tickers_loaded: int
    alpaca_enabled: bool
    enrich_enabled: bool
    enrich_model: str | None
    sources: list[SourceStatus]
    admin: AdminStatus


# --- Research studies --------------------------------------------------------------------


class StudyInfo(BaseModel):
    study: Literal["main", "oos", "insider_purchases"]
    available: bool
    generated_at: str | None = None
    n_tests: int | None = None
    design: str | None = None  # config.study in the result file


# --- Journal hash chain (app/journal/digest.py) ----------------------------------------------


class ChainLine(BaseModel):
    day: str
    prev_hash: str
    hash: str
    count: int | None = None
    sealed_at: str | None = None
    sealed_late: bool = False


class ChainHead(BaseModel):
    head_hash: str
    head_day: str
    days: int


class JournalChain(BaseModel):
    head: ChainHead | None
    lines: list[ChainLine]  # the last 30 sealed days, oldest first
    error: str | None = None  # the chain file is malformed


class ChainDay(BaseModel):
    day: str
    prev_hash: str
    hash: str
    entries: list[dict]  # canonical record-time fields, enough to recompute the hash


class ChainVerify(BaseModel):
    ok: bool
    days: int
    head_hash: str | None
    head_day: str | None
    first_mismatch: dict | None
    broken_link: dict | None
    late_days: list[str]
    checked_at: datetime  # verify_chain is cached for up to 10 minutes


# --- Health (app/health.py) ------------------------------------------------------------------

HealthState = Literal["ok", "degraded", "down", "disabled", "unknown"]


class HealthComponent(BaseModel):
    model_config = ConfigDict(extra="allow")  # component-specific fields (age_seconds, latest_issue, enabled, ...)

    status: HealthState
    detail: str | None = None


class HealthDetails(BaseModel):
    status: Literal["ok", "degraded", "down"]
    checked_at: datetime
    components: dict[str, HealthComponent]
    thresholds: dict


class UptimeStat(BaseModel):
    uptime_pct: float | None
    samples: int


class UptimeDay(BaseModel):
    day: str
    uptime_pct: float | None
    samples: int


class HealthIncident(BaseModel):
    """A status change between two consecutive uptime samples. JSON keys: at, component, from, to."""

    model_config = ConfigDict(populate_by_name=True)

    at: str
    component: str  # "overall" or a component name
    from_: str = Field(alias="from")
    to: str


class HealthHistory(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    days: int
    from_: str = Field(alias="from")
    to: str
    samples: int
    uptime_pct: float | None
    components: dict[str, UptimeStat]
    daily: list[UptimeDay]
    incidents: list[HealthIncident]
