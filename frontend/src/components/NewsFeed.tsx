"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import ArticleCard from "@/components/ArticleCard";
import Sidebar from "@/components/Sidebar";
import { api, type Article, type ArticleFilters } from "@/lib/api";
import { SIZE_FILTERS } from "@/lib/format";

const EVENT_TYPES = [
  "earnings", "guidance", "m&a", "deal", "analyst", "management", "legal", "regulatory",
  "product", "macro", "bankruptcy", "restructuring", "accounting", "other",
];

export default function NewsFeed() {
  const [filters, setFilters] = useState<ArticleFilters>({});
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<Article[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [freshIds, setFreshIds] = useState<Set<number>>(new Set());
  const [live, setLive] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const itemsRef = useRef(items);
  itemsRef.current = items;

  const load = useCallback(async (f: ArticleFilters) => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.articles({ ...f, limit: 50 });
      setItems(page.items);
      setNextBefore(page.next_before);
      setPending(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(filters);
  }, [filters, load]);

  // Debounce the search box into filters.q
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => (f.q === search ? f : { ...f, q: search || undefined })), 300);
    return () => clearTimeout(t);
  }, [search]);

  const unfiltered = !filters.q && !filters.ticker && !filters.source && !filters.sentiment && !filters.event_type && !filters.size;

  // Live updates over server-sent events
  useEffect(() => {
    const es = new EventSource(api.streamUrl);
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.addEventListener("article", async (ev) => {
      const { id } = JSON.parse((ev as MessageEvent).data);
      if (!unfiltered) {
        setPending((n) => n + 1);
        return;
      }
      const article = await api.article(id).catch(() => null);
      if (!article || itemsRef.current.some((a) => a.id === id)) return;
      setItems((prev) => [article, ...prev].sort((a, b) => b.published_at.localeCompare(a.published_at)));
      setFreshIds((s) => new Set(s).add(id));
      setRefreshKey((k) => k + 1);
    });
    es.addEventListener("article_updated", async (ev) => {
      const { id } = JSON.parse((ev as MessageEvent).data);
      if (!itemsRef.current.some((a) => a.id === id)) return;
      const article = await api.article(id).catch(() => null);
      if (article) setItems((prev) => prev.map((a) => (a.id === id ? article : a)));
    });
    return () => es.close();
  }, [unfiltered]);

  const loadMore = async () => {
    if (!nextBefore) return;
    const page = await api.articles({ ...filters, before: nextBefore, limit: 50 });
    setItems((prev) => [...prev, ...page.items]);
    setNextBefore(page.next_before);
  };

  const set = (patch: Partial<ArticleFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <div className="layout">
      <main className="feed">
        <div className="toolbar">
          <input
            type="search"
            placeholder="Search headlines…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="search"
          />
          <input
            placeholder="Ticker"
            value={filters.ticker ?? ""}
            onChange={(e) => set({ ticker: e.target.value.toUpperCase() || undefined })}
            className="ticker-input"
          />
          <select value={filters.size ?? ""} onChange={(e) => set({ size: e.target.value || undefined })} aria-label="Company size">
            {SIZE_FILTERS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <select value={filters.source ?? ""} onChange={(e) => set({ source: e.target.value || undefined })}>
            <option value="">All sources</option>
            <option value="rss">News</option>
            <option value="edgar">SEC filings</option>
            <option value="alpaca">Benzinga</option>
          </select>
          <select
            value={filters.sentiment ?? ""}
            onChange={(e) => set({ sentiment: (e.target.value || undefined) as ArticleFilters["sentiment"] })}
          >
            <option value="">Any sentiment</option>
            <option value="positive">Positive</option>
            <option value="neutral">Neutral</option>
            <option value="negative">Negative</option>
          </select>
          <select value={filters.event_type ?? ""} onChange={(e) => set({ event_type: e.target.value || undefined })}>
            <option value="">Any event</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <span className={`live ${live ? "on" : ""}`} title={live ? "Live stream connected" : "Reconnecting…"}>
            {live ? "LIVE" : "OFFLINE"}
          </span>
        </div>

        {pending > 0 && (
          <button className="pending" onClick={() => load(filters)}>
            {pending} new article{pending > 1 ? "s" : ""}. Refresh
          </button>
        )}
        {error && <p className="error">Could not load articles: {error}</p>}
        {loading && items.length === 0 && <p className="muted">Loading…</p>}
        {!loading && !error && items.length === 0 && <p className="muted">No articles match these filters.</p>}

        {items.map((a) => (
          <ArticleCard key={a.id} article={a} fresh={freshIds.has(a.id)} />
        ))}

        {nextBefore && (
          <button className="btn more" onClick={loadMore}>
            Load older
          </button>
        )}
      </main>
      <Sidebar refreshKey={refreshKey} />
    </div>
  );
}
