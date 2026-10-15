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
    benchmark: Record<string, string>;
    price_source: string;
  };
  coverage: Record<string, Record<string, number>>;
  measured_events: number;
  testing: { n_tests: number; t_critical: number };
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
  ingest: () => fetch(`${API_BASE}/api/ingest`, { method: "POST" }).then((r) => r.json()),
  streamUrl: `${API_BASE}/api/stream`,
};
