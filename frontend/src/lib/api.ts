export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Sentiment = "positive" | "negative" | "neutral";

export type SizeBucket = "nano" | "micro" | "small" | "mid" | "large";

export interface Ticker {
  symbol: string;
  method: string;
  size_bucket: SizeBucket | null;
}

export interface Signal {
  code: string;
  label: string;
  direction: "-" | "+" | "?";
  severity: number;
  why: string;
  /** True for forward-test signals (backend pipeline.signals.FORWARD_TEST_SIGNALS). Optional: older APIs omit it. */
  forward_test?: boolean;
}

export interface Evidence {
  signal: string;
  bucket: SizeBucket;
  n: number;
  horizon_days: number;
  mean_abnormal: number;
  mean_net: number;
  excess_vs_baseline: number | null;
  t_stat: number;
  significant: boolean;
  // Optional fields of backend schemas.EvidenceOut (served on articles) for forward-test evidence.
  /** "insider_purchases" for the insider forward test; null/absent = the main event study. */
  study?: string | null;
  /** In-sample result of a pre-registered study, now being forward-tested live. */
  forward_test?: boolean;
  t_stat_clustered?: number | null;
  companies?: number | null;
}

export interface StudyResult extends Evidence {
  label: string;
  direction: "-" | "+" | "?";
  companies: number;
  mean_reaction: number;
  median_abnormal: number;
  hit_rate: number;
  cost: number;
  borrow: number;
  baseline_mean: number | null;
  t_vs_baseline: number | null;
  nominal_significant: boolean;
  /** Firm-clustered (CR1) t-stats, clusters = companies. Reporting only in the main study. Absent on older files. */
  t_stat_clustered?: number | null;
  t_vs_baseline_clustered?: number | null;
  clusters?: number;
}

export type StudyName = "main" | "oos" | "insider_purchases";

/** One pre-registered out-of-sample hypothesis (backend/app/research/oos.py `confirmatory`). Historical, hypothetical. */
export interface ConfirmatoryResult {
  hypothesis: string;
  signal: string;
  label: string;
  buckets: string[];
  cells: string[];
  horizon_days: number;
  direction: "-" | "+" | "?";
  n: number;
  companies: number;
  mean_abnormal: number | null;
  baseline_mean: number | null;
  excess_vs_baseline: number | null;
  t_clustered: number | null;
  t_vs_baseline_clustered: number | null;
  mean_net: number | null;
  t_critical: number;
  checks: Record<string, boolean>;
  verdict: "replicated" | "not replicated" | "underpowered";
}

export interface EventStudy {
  generated_at: string;
  config: {
    window: [string, string];
    size_measured: string;
    sample_sizes: Record<string, number>;
    horizons: number[];
    min_n: number;
    costs_round_trip: Record<string, number>;
    borrow_apr_for_shorts?: Record<string, number>;
    benchmark: Record<string, string>;
    price_source: string;
    /** StudyDesign name: "in_sample", "oos", "insider_purchases". Absent on older files. */
    study?: string;
    design?: Record<string, unknown>;
  };
  coverage: Record<string, Record<string, number>>;
  measured_events: number;
  testing: { n_tests: number; t_critical: number; baseline: Record<string, Record<string, number>>; role?: string };
  results: StudyResult[];
  caveats: string[];
  /** OOS study only: the pre-registered confirmatory tests (results[] there is exploratory). */
  confirmatory?: ConfirmatoryResult[];
  confirmatory_testing?: { family_size: number; alpha_two_sided: number; t_critical: number; min_n: number; min_companies: number; statistic: string };
  preregistration?: string;
  preregistered_on?: string;
}

/** GET /api/research/studies (schemas.StudyInfo). */
export interface StudyInfo {
  study: StudyName;
  available: boolean;
  generated_at: string | null;
  n_tests: number | null;
  design: string | null;
}

export interface Article {
  id: number;
  url: string;
  title: string;
  snippet: string | null;
  source: string;
  source_name: string;
  author: string | null;
  published_at: string;
  ai_summary: string | null;
  sentiment: number | null;
  sentiment_label: Sentiment | null;
  event_type: string | null;
  relevance: number | null;
  enrich_model: string | null;
  tickers: Ticker[];
  form: string | null;
  severity: number | null;
  signals: Signal[];
  ai_flags: string[] | null;
  evidence: Evidence[];
  /** Any signal is a forward-test signal (label: forward test of pre-registered finding). Optional: older APIs omit it. */
  forward_test?: boolean;
}

export interface ArticlePage {
  items: Article[];
  next_before: string | null;
}

export interface TrendingTicker {
  symbol: string;
  name: string | null;
  mentions: number;
  avg_sentiment: number | null;
  size_bucket: SizeBucket | null;
}

export interface TickerDetail {
  symbol: string;
  name: string | null;
  cik: number | null;
  public_float: number | null;
  float_as_of: string | null;
  size_bucket: SizeBucket | null;
  on_watchlist: boolean;
  mentions: number;
  avg_sentiment: number | null;
  daily: { day: string; mentions: number; avg_sentiment: number | null }[];
  articles: Article[];
}

export interface Status {
  articles: number;
  enriched: number;
  tickers_loaded: number;
  alpaca_enabled: boolean;
  enrich_enabled: boolean;
  enrich_model: string | null;
  sources: { name: string; last_run: string | null; fetched: number | null; inserted: number | null; error: string | null }[];
  /** Mutation protection (schemas.AdminStatus). Never includes the token. */
  admin: AdminStatus;
}

export interface AdminStatus {
  /** An admin token is configured: mutations need it. */
  protected: boolean;
  /** Ingest, alerts/test and watchlist changes are possible at all on this server. */
  mutations_enabled: boolean;
}

// --- Health (mirrors schemas.HealthDetails / HealthHistory, backend/app/health.py) ---

export type HealthState = "ok" | "degraded" | "down" | "disabled" | "unknown";

export interface HealthComponent {
  status: HealthState;
  detail: string | null;
  age_seconds?: number | null;
  last_mark?: string | null;
  latest_issue?: string | null;
  week_end?: string | null;
  enabled?: boolean;
  channel?: string;
  last?: { status: string; reason: string | null; at: string } | null;
  active?: string | null;
}

export interface HealthDetails {
  status: "ok" | "degraded" | "down";
  checked_at: string;
  components: Record<string, HealthComponent>;
  thresholds: { ingest_stale_seconds: number; edgar_stale_seconds: number; edgar_hours_et: string; critical: string[] };
}

export interface HealthIncident {
  at: string;
  component: string;
  from: string;
  to: string;
}

export interface HealthHistory {
  days: number;
  from: string;
  to: string;
  samples: number;
  uptime_pct: number | null;
  components: Record<string, { uptime_pct: number | null; samples: number }>;
  daily: { day: string; uptime_pct: number | null; samples: number }[];
  incidents: HealthIncident[];
}

// --- Journal hash chain (mirrors schemas.JournalChain / ChainDay / ChainVerify, backend/app/journal/digest.py) ---

export interface ChainLine {
  day: string;
  prev_hash: string;
  hash: string;
  count: number | null;
  sealed_at: string | null;
  sealed_late: boolean;
}

export interface JournalChain {
  head: { head_hash: string; head_day: string; days: number } | null;
  /** Last 30 sealed days, oldest first. */
  lines: ChainLine[];
  error: string | null;
}

export interface ChainDay {
  day: string;
  prev_hash: string;
  hash: string;
  entries: Record<string, unknown>[];
}

export interface ChainVerify {
  ok: boolean;
  days: number;
  head_hash: string | null;
  head_day: string | null;
  first_mismatch: { day: string; expected: string; actual: string } | null;
  broken_link: { day: string | null; expected_prev: string | null; actual_prev: string | null; reason: string } | null;
  late_days: string[];
  /** verify_chain is cached server-side for up to 10 minutes. */
  checked_at: string;
}

// --- Backtest (mirrors backend/app/backtest/report.py) ---

export interface BacktestMetrics {
  start: string | null;
  end: string | null;
  start_equity: number;
  end_equity: number;
  total_return: number;
  cagr: number;
  volatility: number;
  sharpe: number;
  sortino: number;
  max_drawdown: number;
  longest_drawdown_days: number;
  calmar: number | null;
  skew: number;
  kurtosis: number;
  avg_gross_exposure: number;
  time_in_market: number;
  psr: number;
  worst_month: number;
  trades: number;
  win_rate?: number;
  avg_win?: number;
  avg_loss?: number;
  profit_factor?: number | null;
  avg_trade_return?: number;
  median_trade_return?: number;
  best_trade_return?: number;
  worst_trade_return?: number;
  avg_days_held?: number;
  exit_reasons?: Record<string, number>;
  total_costs?: number;
  total_borrow?: number;
  signals: number;
  fill_rate: number;
  skipped: Record<string, number>;
}

export interface BacktestTrade {
  ticker: string;
  company: string;
  form: string;
  filed: string;
  filing_url: string;
  public_float: number;
  entry_date: string;
  exit_date: string;
  days_held: number;
  entry_price: number;
  exit_move: number;
  notional: number;
  short_pnl: number;
  hedge_pnl: number;
  costs: number;
  borrow: number;
  net_pnl: number;
  net_return: number;
  exit_reason: string;
}

export interface StressRow {
  label: string;
  changes: Record<string, unknown>;
  total_return: number;
  cagr: number;
  sharpe: number;
  max_drawdown: number;
  trades: number;
}

export interface CapacityRow {
  capital: number;
  total_return: number;
  cagr: number;
  sharpe: number;
  max_drawdown: number;
  trades: number;
  fill_rate: number;
}

export interface BacktestPeriod {
  period: { key: string; label: string; role: "out_of_sample" | "discovery"; float_year: number; start: string; end: string };
  metrics: BacktestMetrics;
  bootstrap: Record<string, number>;
  equity_curve: [string, number][];
  drawdown_curve: [string, number][];
  exposure_curve: [string, number][];
  monthly_returns: Record<string, number>;
  yearly_returns: Record<string, number>;
  trades: BacktestTrade[];
  skipped_sample: { ticker: string; accepted: string; reason: string }[];
  stress: StressRow[];
  capacity: CapacityRow[];
  monte_carlo: Record<string, number>;
  by_form: Record<string, { trades: number; avg_return: number; win_rate: number; net_pnl: number }>;
  min_track_record_days: number | null;
  waterfall: { step: string; trades: number; avg_trade_return: number; median_trade_return: number; total_return: number; sharpe: number }[];
  borrow_sensitivity: { rows: { borrow_apr: number; total_return: number; cagr: number; sharpe: number }[]; breakeven_apr: number | null };
}

export interface ReadinessGate {
  gate: string;
  status: "pass" | "fail" | "pending";
  value: unknown;
  threshold: string;
  why: string;
}

export interface BacktestReport {
  generated_at: string;
  strategy: { id: string; name: string; summary: string; hypothesis: string };
  base_config: Record<string, unknown>;
  coverage: Record<string, Record<string, number>>;
  periods: Record<string, BacktestPeriod>;
  walk_forward: {
    train_period: string;
    test_period: string;
    grid: { params: Record<string, unknown>; train_sharpe: number; train_return: number }[];
    chosen: Record<string, unknown>;
    test: Record<string, number>;
  };
  /**
   * trials, dsr_<period>, luck_sharpe_<period>; newer reports also n_returns_<period> (daily returns the DSR used)
   * and trial_sharpe_std (sd of the trial Sharpes, annual). Older reports lack the last two.
   */
  overfitting: Record<string, number> & { trials?: number; trial_sharpe_std?: number };
  borrow_check: Record<string, unknown>;
  readiness: ReadinessGate[];
  verdict: { level: "not_ready" | "paper_next"; headline: string; detail: string };
  key_finding: { text: string; breakeven_apr_A: number | null; breakeven_apr_B: number | null };
  live_projection: {
    basis: string;
    expected_annual_return_range: (number | null)[];
    prob_losing_year: number | null;
    worst_month: number;
    max_drawdown: number;
    worst_case_stress_cagr: number;
    capacity: CapacityRow[];
    not_modeled: string[];
  };
  assumptions: string[];
}

export interface BacktestRunLog {
  total: number;
  distinct_configs: number;
  search_trials: number;
  runs: {
    id: string;
    at: string;
    strategy: string;
    period: string;
    label: string;
    config_key: string;
    config: Record<string, unknown>;
    signals: number;
    metrics: Record<string, number | null>;
    git: string | null;
  }[];
}

// --- Forward signal journal (mirrors /api/journal* in backend/app/main.py) ---

export type JournalStatus = "waiting" | "open" | "complete" | "data_ended" | "no_data";

/** One JournalEntry row (backend/app/models.py) plus the filing title, URL and signal label. */
export interface JournalEntry {
  id: number;
  article_id: number;
  ticker: string;
  cik: number | null;
  form: string | null;
  signals: string[];
  primary_signal: string;
  direction: "-" | "+" | "?";
  severity: number;
  size_bucket: SizeBucket | null;
  public_float: number | null;
  filed_at: string;
  created_at: string;
  borrow_fee: number | null; // annual fraction (0.05 = 5%/yr)
  borrow_available: number | null; // shares; -1 = plenty
  borrow_snapshot: string | null;
  status: JournalStatus;
  entry_date: string | null;
  entry_price: number | null;
  raw_entry_price: number | null;
  abn_1: number | null;
  abn_5: number | null;
  abn_20: number | null;
  marked_at: string | null;
  title: string;
  filing_url: string;
  signal_label: string;
  /** Trading days the signal is judged on (backend journal.service.evaluation_horizon: 5 or 20). */
  evaluation_horizon?: number | null;
  /** "forward test of pre-registered finding" for forward-test signals, else null. */
  forward_test_label?: string | null;
}

export interface JournalPage {
  total: number;
  since: string | null;
  entries: JournalEntry[];
}

export interface JournalFilters {
  signal?: string;
  size?: string;
  status?: string;
  limit?: number;
}

/** Live results per (primary signal, size bucket); h in 1, 5, 20. expected_h is the Edge Lab mean abnormal return. */
export interface JournalSummaryRow {
  signal: string;
  label: string;
  direction: "-" | "+" | "?";
  bucket: string;
  n: number;
  n_1: number;
  mean_1: number | null;
  median_1: number | null;
  hit_1: number | null;
  expected_1: number | null;
  n_5: number;
  mean_5: number | null;
  median_5: number | null;
  hit_5: number | null;
  expected_5: number | null;
  n_20: number;
  mean_20: number | null;
  median_20: number | null;
  hit_20: number | null;
  expected_20: number | null;
  evaluation_horizon?: number | null;
  forward_test_label?: string | null;
}

export interface JournalSummary {
  rows: JournalSummaryRow[];
  marked: string | null;
}

// --- Hypothetical paper portfolio (mirrors PaperPortfolioOut in backend/app/schemas.py, app/paper/service.py) ---
// Simulated from the forward journal: not traded, not investment advice. There is no execution path.

export interface PaperAssumptions {
  notional: number;
  max_concurrent: number;
  hedge: boolean;
  starting_capital: number;
  cost_model: string;
  horizons: Record<string, number>; // "default" plus per-signal horizons (trading days)
}

export interface PaperEquityPoint {
  date: string;
  equity: number;
  open_positions: number;
}

export interface PaperTotals {
  pnl: number;
  return_pct: number; // fraction of starting capital
  n_closed: number;
  n_open: number;
  hit_rate: number | null;
  skipped_capacity: number;
  unpriced: number;
  pending: number;
  undirected: number;
}

export interface PaperSignalRow {
  signal: string;
  label: string;
  direction: "-" | "+" | "?";
  horizon: number;
  forward_test: boolean;
  forward_test_label: string | null;
  n: number;
  n_closed: number;
  pnl: number;
  mean_return_net: number | null;
  hit_rate: number | null;
}

export interface PaperPosition {
  ticker: string;
  signal: string;
  side: "long" | "short";
  size_bucket: SizeBucket | null;
  horizon: number;
  entry_date: string;
  exit_date: string | null;
  status: "open" | "closed";
  net_return: number;
  pnl: number;
}

export interface PaperPortfolio {
  as_of: string;
  label: string;
  assumptions: PaperAssumptions;
  equity_curve: PaperEquityPoint[];
  totals: PaperTotals;
  by_signal: PaperSignalRow[];
  positions: PaperPosition[]; // most recent 50
  empty_reason: string | null;
}

export interface PaperPortfolioParams {
  hedge?: boolean;
  max_concurrent?: number; // 1..100, default 20
}

export interface Fundamentals {
  cik: number;
  cash: { value: number; as_of: string; tag: string; short_term_investments?: number } | null;
  operating_cash_flow: { value: number; period_end: string; method: string } | null;
  runway: { status: "unknown" | "cash_flow_positive" | "burning"; monthly_burn?: number; months?: number | null; runs_out_around?: string | null };
  shares_history: { date: string; shares: number }[];
  share_change_1y: { from: string; to: string; change: number; days: number } | null;
  dilution_filings: { form: string; filed: string; kind: string; url: string }[];
  offerings_last_12m: number;
  raises_since_cash_date: number;
  short_interest: {
    date: string;
    shares_short: number;
    days_to_cover: number | null;
    change_pct: number | null;
    pct_of_shares_outstanding: number | null;
    history: { date: string; shares_short: number; days_to_cover: number | null }[];
  } | null;
}

export interface Halt {
  symbol: string;
  name: string;
  market: string;
  reason_code: string;
  reason: string;
  serious: boolean;
  halted_at: string;
  resumed_at: string | null;
  size_bucket: SizeBucket | null;
}

// --- Weekly newsletter (mirrors backend/app/newsletter/service.py build_issue) ---

export type Direction = "-" | "+" | "?";

export interface NewsletterSignal {
  code: string;
  label: string;
  direction: Direction;
  severity: number;
}

/**
 * Edge Lab 20-day row for the filing's signal and size: historical, hypothetical.
 * The backend copies these with `row.get(k)` from event_study.json, so every stat can be null
 * (the newsletter renderers then omit the evidence line when `mean_abnormal` is null).
 */
export interface NewsletterEvidence {
  signal: string;
  label: string;
  n: number | null;
  horizon_days: number | null;
  mean_abnormal: number | null;
  median_abnormal: number | null;
  excess_vs_baseline: number | null;
  t_stat: number | null;
  significant: boolean | null;
}

export interface NewsletterFiling {
  article_id: number;
  ticker: string;
  company: string;
  size: SizeBucket;
  public_float: number | null;
  form: string | null;
  severity: number;
  signals: NewsletterSignal[];
  filed_at: string;
  url: string;
  evidence: NewsletterEvidence | null;
}

export interface NewsletterRunway {
  status: "unknown" | "cash_flow_positive" | "burning";
  months: number | null;
  runs_out_around: string | null;
  cash_as_of: string | null;
  stale?: boolean;
}

export interface NewsletterDilution {
  ticker: string;
  company: string;
  size: SizeBucket;
  public_float: number | null;
  offering_signals: number;
  priced: boolean;
  filings: { form: string | null; signals: string[]; filed_at: string; url: string }[];
  runway: NewsletterRunway | null;
  reasons: string[];
}

export interface NewsletterHalt {
  symbol: string;
  name: string;
  market: string;
  reason_code: string;
  reason: string;
  halted_at: string;
  resumed_at: string | null;
  size: SizeBucket | null;
}

export interface NewsletterTrackRow {
  signal: string;
  label: string;
  direction: Direction;
  bucket: string;
  n: number;
  n_20: number;
  mean_20: number | null;
  median_20: number | null;
  hit_20: number | null;
  expected_20: number | null;
}

export interface NewsletterHeadline {
  signal_filings: number;
  companies: number;
  by_severity: Record<"1" | "2" | "3", number>;
  by_size: Record<"nano" | "micro" | "small", number>;
  dilution_watch: number;
  serious_halts: number;
}

export interface NewsletterIssueSummary {
  id: string;
  title: string;
  week_start: string;
  week_end: string;
  generated_at: string;
  headline: NewsletterHeadline;
}

export interface NewsletterIssue extends NewsletterIssueSummary {
  partial: boolean;
  data_through: string;
  base_url: string;
  sources_note: string;
  coverage_note: string | null;
  top_filings: NewsletterFiling[];
  top_filings_total: number;
  dilution_watch: NewsletterDilution[];
  runway_lookups: number;
  serious_halts: NewsletterHalt[];
  serious_halts_total: number;
  track_record: {
    recorded: number;
    complete_20d: number;
    min_n: number;
    rows: NewsletterTrackRow[];
    collecting: { recorded: number; first_due: string | null } | null;
    /** Journal hash-chain head at build time; null without a chain, absent on issues archived before the seal existed. */
    seal?: { head_hash: string; head_day: string; days: number } | null;
  };
  research_note: { text: string; strategy: string | null; report_date: string | null } | null;
  links: Record<"methodology" | "track_record" | "edge_lab" | "disclaimer" | "archive", string>;
  disclaimer: string[];
  /** Banned words found in our own prose (company names and tickers excluded); [] normally, absent on older issues. */
  flagged_words?: string[];
  markdown: string;
  html?: string; // only on the preview response
}

export interface ArticleFilters {
  q?: string;
  ticker?: string;
  source?: string;
  sentiment?: Sentiment | "";
  event_type?: string;
  size?: string;
  watchlist?: boolean;
  signal?: string;
  min_severity?: number;
  before?: string;
  limit?: number;
}

/** Non-2xx response. `message` starts with the status ("404 ...") so callers can keep checking `startsWith("404")`. */
export class ApiError extends Error {
  /** `admin`: raised by an admin-protected call (send with admin: true). */
  constructor(public status: number, message: string, public detail?: string, public admin = false) {
    super(message);
    this.name = "ApiError";
  }
}

/** An ApiError from an admin-protected call that the user can act on: 401 (token), 403 (disabled), 429 (rate limit). */
export function isAdminApiError(e: unknown): e is ApiError {
  return e instanceof ApiError && e.admin && (e.status === 401 || e.status === 403 || e.status === 429);
}

// --- Admin token (this browser tab only) ---
// Sent as a Bearer header on every admin-protected call. sessionStorage can be unavailable (privacy modes, SSR):
// these helpers never throw.
const ADMIN_TOKEN_KEY = "undertow.researchAdminToken";

export function getAdminToken(): string {
  try {
    return typeof window === "undefined" ? "" : (window.sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? "");
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (typeof window === "undefined") return;
    if (token.trim()) window.sessionStorage.setItem(ADMIN_TOKEN_KEY, token.trim());
    else window.sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    /* storage unavailable: the token just isn't kept */
  }
}

export const ADMIN_TOKEN_REQUIRED = "Admin token required. Enter it on the Status page (kept for this browser tab only).";
export const CHANGES_DISABLED = "Changes are turned off on this server.";

async function errorFor(res: Response, admin: boolean): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  const detail = typeof body?.detail === "string" ? body.detail : undefined;
  if (admin && res.status === 401) return new ApiError(401, `401 ${ADMIN_TOKEN_REQUIRED}`, detail, admin);
  if (admin && res.status === 403) return new ApiError(403, `403 ${CHANGES_DISABLED} ${detail ?? ""}`.trim(), detail, admin);
  if (res.status === 429) return new ApiError(429, `429 Too many requests. Try again in ${res.headers.get("Retry-After") ?? "a few"} seconds.`, detail, admin);
  return new ApiError(res.status, `${res.status} ${detail ?? res.statusText}`, detail, admin);
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`);
  return res.json();
}

/**
 * Mutating request. `admin`: attach the tab's admin token (if any) and turn 401/403 into a clear message.
 * Public writes (subscribe, newsletter preview) send no token.
 */
async function send<T>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  opts: { admin?: boolean; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = opts.admin ? getAdminToken() : "";
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    cache: "no-store",
    signal: opts.timeoutMs ? AbortSignal.timeout(opts.timeoutMs) : undefined,
  });
  if (!res.ok) throw await errorFor(res, !!opts.admin);
  return res.json();
}

function query(params: object): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

/** backend/app/research_jobs.py MODULES. */
export type ResearchJobKind = "backtest" | "event_study" | "event_study_oos" | "insider_study";
export interface ResearchJob {
  id: string;
  kind: ResearchJobKind;
  status: "running" | "succeeded" | "failed" | "interrupted";
  started_at: string;
  finished_at: string | null;
  message: string;
}
export interface ResearchJobs {
  active: ResearchJob | null;
  latest: Partial<Record<ResearchJobKind, ResearchJob | null>>;
  /** False when this server does not accept launches from the UI (e.g. a public deployment without an admin token). */
  enabled: boolean;
  /** True when launches need the operator's admin token (ADMIN_TOKEN, or the older RESEARCH_ADMIN_TOKEN, on the API). */
  requires_token: boolean;
}

export const api = {
  researchJobs: async () => {
    const res = await fetch(`${API_BASE}/api/research/jobs`, { cache: "no-store", signal: AbortSignal.timeout(15000) });
    if (!res.ok) throw await errorFor(res, false);
    return (await res.json()) as ResearchJobs;
  },
  /** Uses the tab's admin token (setAdminToken). ApiError 401: token missing/wrong; 403: runs disabled on this server. */
  startResearch: (kind: ResearchJobKind) =>
    send<ResearchJob>(`/api/research/jobs/${kind}`, "POST", { admin: true, timeoutMs: 15000 }),
  articles: (f: ArticleFilters = {}) => get<ArticlePage>(`/api/articles${query(f)}`),
  article: (id: number) => get<Article>(`/api/articles/${id}`),
  signals: (f: ArticleFilters = {}) => get<ArticlePage>(`/api/signals${query(f)}`),
  signalCatalog: () => get<Signal[]>("/api/signals/catalog"),
  /** study defaults to "main" (the live evidence). 404 when that study has not been run. */
  eventStudy: (study: StudyName = "main") =>
    get<EventStudy>(study === "main" ? "/api/research/event-study" : `/api/research/event-study?study=${study}`),
  studies: () => get<StudyInfo[]>("/api/research/studies"),
  watchlist: () => get<TrendingTicker[]>("/api/watchlist"),
  /** Admin-protected. Throws ApiError: 401 -> ADMIN_TOKEN_REQUIRED, 403 -> CHANGES_DISABLED, 404 unknown ticker. */
  watch: (symbol: string, on: boolean) =>
    send<{ symbol: string; on_watchlist: boolean }>(`/api/watchlist/${encodeURIComponent(symbol)}`, on ? "PUT" : "DELETE", { admin: true }),
  trending: (hours = 24, size = "") => get<TrendingTicker[]>(`/api/tickers/trending${query({ hours, size })}`),
  halts: (f: { symbol?: string; size?: string; hours?: number; limit?: number } = {}) => get<Halt[]>(`/api/halts${query(f)}`),
  fundamentals: (symbol: string) => get<Fundamentals>(`/api/tickers/${encodeURIComponent(symbol)}/fundamentals`),
  ticker: (symbol: string, days = 30) => get<TickerDetail>(`/api/tickers/${encodeURIComponent(symbol)}?days=${days}`),
  status: () => get<Status>("/api/status"),
  backtestReport: () => get<BacktestReport>("/api/backtest/report"),
  backtestRuns: (limit = 200) => get<BacktestRunLog>(`/api/backtest/runs?limit=${limit}`),
  journal: (f: JournalFilters = {}) => get<JournalPage>(`/api/journal${query(f)}`),
  journalSummary: () => get<JournalSummary>("/api/journal/summary"),
  journalChain: () => get<JournalChain>("/api/journal/chain"),
  journalChainDay: (day: string) => get<ChainDay>(`/api/journal/chain/${encodeURIComponent(day)}`),
  journalVerify: () => get<ChainVerify>("/api/journal/verify"),
  /** Hypothetical paper portfolio simulated from the journal (read-only). */
  paperPortfolio: (p: PaperPortfolioParams = {}) => get<PaperPortfolio>(`/api/paper-portfolio${query(p)}`),
  healthDetails: () => get<HealthDetails>("/api/health/details"),
  healthHistory: (days = 7) => get<HealthHistory>(`/api/health/history?days=${days}`),
  /** 202 with a generic message (no enumeration); ApiError 503 when email delivery is not configured. */
  subscribe: (email: string, daily = false) => send<{ message: string }>("/api/subscribe", "POST", { body: { email, daily } }),
  newsletterIssues: () => get<NewsletterIssueSummary[]>("/api/newsletter/issues"),
  newsletterIssue: (id: string) => get<NewsletterIssue>(`/api/newsletter/${encodeURIComponent(id)}`),
  newsletterHtmlUrl: (id: string) => `${API_BASE}/api/newsletter/${encodeURIComponent(id)}.html`,
  newsletterHtml: (id: string) =>
    fetch(`${API_BASE}/api/newsletter/${encodeURIComponent(id)}.html`, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      return r.text();
    }),
  newsletterPreview: () => send<NewsletterIssue>("/api/newsletter/preview", "POST"),
  /** Admin-protected. Throws ApiError (401 -> ADMIN_TOKEN_REQUIRED, 403 -> CHANGES_DISABLED). */
  ingest: () => send<Record<string, unknown>>("/api/ingest", "POST", { admin: true }),
  streamUrl: `${API_BASE}/api/stream`,
};
