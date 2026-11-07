"use client";

import { useEffect, useState } from "react";

import ArticleCard from "@/components/ArticleCard";
import { useFeed } from "@/components/feed/useFeed";
import Sidebar from "@/components/Sidebar";
import { api, type ArticleFilters } from "@/lib/api";
import { SIZE_FILTERS } from "@/lib/format";

const EVENT_TYPES = [
  "earnings", "guidance", "m&a", "deal", "analyst", "management", "legal", "regulatory",
  "product", "macro", "bankruptcy", "restructuring", "impairment", "accounting", "listing",
  "offering", "activist", "disclosure", "other",
];

export default function NewsFeed() {
  const [filters, setFilters] = useState<ArticleFilters>({ size: "all" });
  const [search, setSearch] = useState("");
  const { items, nextBefore, loading, loadingMore, error, pending, live, refresh, loadMore, retry } = useFeed(api.articles, filters);

  // Debounce the search box into filters.q
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => ((f.q ?? "") === search ? f : { ...f, q: search || undefined })), 300);
    return () => clearTimeout(t);
  }, [search]);

  const set = (patch: Partial<ArticleFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <div className="layout">
      <main className="feed">
        <div className="toolbar">
          <input
            type="search"
            aria-label="Search headlines"
            placeholder="Search headlines…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="search"
          />
          <input
            placeholder="Ticker"
            aria-label="Ticker"
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
          <select aria-label="Source" value={filters.source ?? ""} onChange={(e) => set({ source: e.target.value || undefined })}>
            <option value="">All sources</option>
            <option value="rss">News</option>
            <option value="edgar">SEC filings</option>
            <option value="alpaca">Benzinga</option>
          </select>
          <select
            aria-label="Sentiment"
            value={filters.sentiment ?? ""}
            onChange={(e) => set({ sentiment: (e.target.value || undefined) as ArticleFilters["sentiment"] })}
          >
            <option value="">Any sentiment</option>
            <option value="positive">Positive</option>
            <option value="neutral">Neutral</option>
            <option value="negative">Negative</option>
          </select>
          <select aria-label="Event type" value={filters.event_type ?? ""} onChange={(e) => set({ event_type: e.target.value || undefined })}>
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

        {pending && (
          <button className="pending" onClick={refresh} disabled={loading || loadingMore}>
            Feed updates available. Refresh
          </button>
        )}
        {error && <p className="error" role="alert">Could not load articles: {error}. <button className="btn" onClick={retry} disabled={loading || loadingMore}>Retry</button></p>}
        {loading && <p className="muted" role="status">Loading articles...</p>}
        {!loading && !error && items.length === 0 && <p className="empty-state">No articles match these filters yet. New filings and headlines appear here as each ingest cycle runs.</p>}

        {items.map((a) => (
          <ArticleCard key={a.id} article={a} />
        ))}

        {nextBefore && (
          <button className="btn more" onClick={loadMore} disabled={loading || loadingMore}>
            {loadingMore ? "Loading older..." : "Load older"}
          </button>
        )}
      </main>
      <Sidebar refreshKey={pending ? 1 : 0} />
    </div>
  );
}
