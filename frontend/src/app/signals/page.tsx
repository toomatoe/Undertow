"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useFeed } from "@/components/feed/useFeed";
import ArticleCard from "@/components/ArticleCard";
import HaltsPanel from "@/components/HaltsPanel";
import WatchlistPanel from "@/components/WatchlistPanel";
import { api, type ArticleFilters, type Signal } from "@/lib/api";
import { SIZE_FILTERS } from "@/lib/format";

export default function SignalsPage() {
  const [filters, setFilters] = useState<ArticleFilters>({ size: "nano,micro,small", min_severity: 1 });
  const [catalog, setCatalog] = useState<Signal[]>([]);
  const { items, nextBefore, loading, loadingMore, error, pending, refresh, loadMore, retry } = useFeed(api.signals, filters);

  useEffect(() => {
    api.signalCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, []);

  const set = (patch: Partial<ArticleFilters>) => setFilters((f) => ({ ...f, ...patch }));

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

        {pending && <button className="pending" onClick={refresh} disabled={loading || loadingMore}>Feed updates available. Refresh</button>}
        {error && <p className="error" role="alert">Could not load signals: {error}. <button className="btn" onClick={retry} disabled={loading || loadingMore}>Retry</button></p>}
        {loading && <p className="muted" role="status">Loading signals...</p>}
        {!loading && !error && items.length === 0 && (
          <p className="empty-state">
            No signals match yet: the poller adds them as new filings arrive on EDGAR. Filings older than the app&apos;s first run are not loaded.
          </p>
        )}
        {items.map((a) => (
          <ArticleCard key={a.id} article={a} />
        ))}
        {nextBefore && (
          <button className="btn more" onClick={loadMore} disabled={loading || loadingMore}>
            {loadingMore ? "Loading older..." : "Load older"}
          </button>
        )}
      </main>
      <aside className="sidebar">
        <WatchlistPanel onChange={() => filters.watchlist && refresh()} />
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
