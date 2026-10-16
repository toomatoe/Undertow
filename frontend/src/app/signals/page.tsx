"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import ArticleCard from "@/components/ArticleCard";
import HaltsPanel from "@/components/HaltsPanel";
import WatchlistPanel from "@/components/WatchlistPanel";
import { api, type Article, type ArticleFilters, type Signal } from "@/lib/api";
import { SIZE_FILTERS } from "@/lib/format";

export default function SignalsPage() {
  const [filters, setFilters] = useState<ArticleFilters>({ size: "nano,micro,small", min_severity: 1 });
  const [items, setItems] = useState<Article[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (f: ArticleFilters) => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.signals({ ...f, limit: 50 });
      setItems(page.items);
      setNextBefore(page.next_before);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(filters);
  }, [filters, load]);

  useEffect(() => {
    api.signalCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, []);

  // New filings arrive through the same SSE stream as news
  useEffect(() => {
    const es = new EventSource(api.streamUrl);
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Batch bursts of new items (an ingest cycle inserts many at once) into one reload
    es.addEventListener("article", () => {
      clearTimeout(timer);
      timer = setTimeout(() => load(filters), 3000);
    });
    return () => {
      clearTimeout(timer);
      es.close();
    };
  }, [filters, load]);

  const set = (patch: Partial<ArticleFilters>) => setFilters((f) => ({ ...f, ...patch }));

  const loadMore = async () => {
    if (!nextBefore) return;
    const page = await api.signals({ ...filters, before: nextBefore, limit: 50 });
    setItems((prev) => [...prev, ...page.items]);
    setNextBefore(page.next_before);
  };

  return (
    <div className="layout">
      <main className="feed">
        <div className="page-intro">
          <h1>Filing signals</h1>
          <p className="muted">
            SEC filings that matter for smaller companies: restatements, auditor changes, delisting notices, dilutive
            offerings, activist stakes. Where the <Link href="/lab">Edge Lab</Link> has history for a signal and size
            bucket, the card shows how similar stocks moved afterwards.
          </p>
        </div>
        <div className="toolbar">
          <select value={filters.size ?? ""} onChange={(e) => set({ size: e.target.value })} aria-label="Company size">
            {SIZE_FILTERS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            value={filters.min_severity ?? 1}
            onChange={(e) => set({ min_severity: Number(e.target.value) })}
            aria-label="Minimum severity"
          >
            <option value={1}>All severities</option>
            <option value={2}>Medium and high</option>
            <option value={3}>High only</option>
          </select>
          <select value={filters.signal ?? ""} onChange={(e) => set({ signal: e.target.value || undefined })} aria-label="Signal">
            <option value="">All signals</option>
            {catalog.map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>
          <label className="check">
            <input type="checkbox" checked={!!filters.watchlist} onChange={(e) => set({ watchlist: e.target.checked || undefined })} />
            Watchlist only
          </label>
        </div>

        {error && <p className="error">Could not load signals: {error}</p>}
        {loading && items.length === 0 && <p className="muted">Loading…</p>}
        {!loading && !error && items.length === 0 && (
          <p className="muted">No filings match. Filings older than the app&apos;s first run are not loaded.</p>
        )}
        {items.map((a) => (
          <ArticleCard key={a.id} article={a} />
        ))}
        {nextBefore && (
          <button className="btn more" onClick={loadMore}>
            Load older
          </button>
        )}
      </main>
      <aside className="sidebar">
        <WatchlistPanel onChange={() => filters.watchlist && load(filters)} />
        <HaltsPanel />
        <section className="panel">
          <h2>Legend</h2>
          <p className="small">
            <span className="dir neg">▼</span> usually negative · <span className="dir pos">▲</span> usually positive ·{" "}
            <span className="dir">◆</span> depends on content
          </p>
          <p className="muted small">
            Size uses SEC-reported public float (shares held by outsiders × price), a conservative proxy for market cap.
          </p>
        </section>
      </aside>
    </div>
  );
}
