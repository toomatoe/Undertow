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
    # True for pipeline.signals.FORWARD_TEST_SIGNALS (live forward test of a separate pre-registered study)
    forward_test: bool = False


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


class EvidenceOut(Evidence):
    """Evidence as served on articles: Evidence plus OPTIONAL fields for forward-test evidence.

    A subclass (not new Evidence fields) because result rows are loaded with Evidence.model_fields as the key
    list (main.load_study, tests/test_insiders.py), and study rows do not carry these keys.
    Main-study evidence serializes with the defaults below.
    """

    study: str | None = None  # "insider_purchases" for the insider forward test; None = the main event study
    forward_test: bool = False  # in-sample result of a pre-registered study, now being forward-tested live
    t_stat_clustered: float | None = None  # firm-clustered t (the insider study's significance rule)
    companies: int | None = None  # distinct companies behind n


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
    evidence: list[EvidenceOut] = []
    forward_test: bool = False  # any signal is a forward-test signal (label: forward test of pre-registered finding)

    @field_validator("signals", mode="before")
    @classmethod
    def expand_signals(cls, v):
        from app.pipeline.signals import signal_def, signal_dict

        if not v:
            return []
        return [signal_dict(signal_def(c)) if isinstance(c, str) else c for c in v if not isinstance(c, str) or signal_def(c) is not None]

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


# --- Paper portfolio (app/paper/service.py): hypothetical, simulated from the journal, never traded -------------


class PaperAssumptions(BaseModel):
    notional: float
    max_concurrent: int
    hedge: bool
    starting_capital: float
    cost_model: str  # where the cost / borrow numbers come from (event study + backtest constants)
    horizons: dict[str, int]  # "default" plus per-signal evaluation horizons (trading days)


class PaperEquityPoint(BaseModel):
    date: str
    equity: float
    open_positions: int


class PaperTotals(BaseModel):
    pnl: float
    return_pct: float  # pnl / starting capital (notional x max_concurrent)
    n_closed: int
    n_open: int
    hit_rate: float | None  # share of closed positions with net return > 0
    skipped_capacity: int  # entries skipped while max_concurrent positions were open
    unpriced: int  # entries without a cached price series (excluded)
    pending: int = 0  # entries the journal has not priced yet (day 0 + 1 not printed)
    undirected: int = 0  # entries whose signal has no expected direction ('?'): no position


class PaperSignalRow(BaseModel):
    signal: str
    label: str
    direction: str
    horizon: int
    forward_test: bool
    forward_test_label: str | None = None
    n: int
    n_closed: int
    pnl: float
    mean_return_net: float | None
    hit_rate: float | None


class PaperPosition(BaseModel):
    ticker: str
    signal: str
    side: Literal["long", "short"]
    size_bucket: str | None = None
    horizon: int
    entry_date: str
    exit_date: str | None
    status: Literal["open", "closed"]
    net_return: float
    pnl: float


class PaperPortfolioOut(BaseModel):
    as_of: str
    label: str  # always the hypothetical label
    assumptions: PaperAssumptions
    equity_curve: list[PaperEquityPoint]
    totals: PaperTotals
    by_signal: list[PaperSignalRow]
    positions: list[PaperPosition]  # most recent 50
    empty_reason: str | None = None


# --- Obsidian vault export (app/vault/AGENTS.md) -------------------------------------------------------------------


class VaultExportResultOut(BaseModel):
    created: int
    updated: int
    unchanged: int
    conflicts: int
    errors: int
    counts: dict[str, int]  # folder -> notes touched (created, updated, unchanged or conflict)
    started_at: str  # ISO UTC
    finished_at: str  # ISO UTC


class VaultStatusOut(BaseModel):
    enabled: bool
    dir: str  # settings.vault_dir (the folder that holds Undertow/)
    last_export_at: str | None  # ISO UTC; null before the first export
    last_result: VaultExportResultOut | None
    conflicts: int  # conflict files waiting in Undertow/_conflicts/
    running: bool


class VaultNoteOut(BaseModel):
    title: str
    path: str  # relative to the vault root, forward slashes
    ticker: str | None
    updated: str | None  # ISO date or timestamp
    tags: list[str]
    excerpt: str


class VaultNotesOut(BaseModel):
    enabled: bool
    ticker: str
    notes: list[VaultNoteOut]
