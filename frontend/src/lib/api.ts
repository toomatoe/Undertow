export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Sentiment = "positive" | "negative" | "neutral";

export interface Ticker {
  symbol: string;
  method: string;
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
}

export interface TickerDetail {
  symbol: string;
  name: string | null;
  cik: number | null;
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
  trending: (hours = 24) => get<TrendingTicker[]>(`/api/tickers/trending?hours=${hours}`),
  ticker: (symbol: string, days = 30) => get<TickerDetail>(`/api/tickers/${encodeURIComponent(symbol)}?days=${days}`),
  status: () => get<Status>("/api/status"),
  ingest: () => fetch(`${API_BASE}/api/ingest`, { method: "POST" }).then((r) => r.json()),
  streamUrl: `${API_BASE}/api/stream`,
};
