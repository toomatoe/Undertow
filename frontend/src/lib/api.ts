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
  };
  coverage: Record<string, Record<string, number>>;
  measured_events: number;
  testing: { n_tests: number; t_critical: number; baseline: Record<string, Record<string, number>> };
  results: StudyResult[];
  caveats: string[];
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
  overfitting: Record<string, number>;
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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
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

export const api = {
  articles: (f: ArticleFilters = {}) => get<ArticlePage>(`/api/articles${query(f)}`),
  article: (id: number) => get<Article>(`/api/articles/${id}`),
  signals: (f: ArticleFilters = {}) => get<ArticlePage>(`/api/signals${query(f)}`),
  signalCatalog: () => get<Signal[]>("/api/signals/catalog"),
  eventStudy: () => get<EventStudy>("/api/research/event-study"),
  watchlist: () => get<TrendingTicker[]>("/api/watchlist"),
  watch: (symbol: string, on: boolean) =>
    fetch(`${API_BASE}/api/watchlist/${encodeURIComponent(symbol)}`, { method: on ? "PUT" : "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      return r.json();
    }),
  trending: (hours = 24, size = "") => get<TrendingTicker[]>(`/api/tickers/trending${query({ hours, size })}`),
  ticker: (symbol: string, days = 30) => get<TickerDetail>(`/api/tickers/${encodeURIComponent(symbol)}?days=${days}`),
  status: () => get<Status>("/api/status"),
  backtestReport: () => get<BacktestReport>("/api/backtest/report"),
  backtestRuns: (limit = 200) => get<BacktestRunLog>(`/api/backtest/runs?limit=${limit}`),
  ingest: () => fetch(`${API_BASE}/api/ingest`, { method: "POST" }).then((r) => r.json()),
  streamUrl: `${API_BASE}/api/stream`,
};
