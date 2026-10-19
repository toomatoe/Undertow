"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api, isAdminApiError, type Status, type TrendingTicker } from "@/lib/api";
import { formatScore, sentimentClass, timeAgo } from "@/lib/format";

export default function Sidebar({ refreshKey }: { refreshKey: number }) {
  const [trending, setTrending] = useState<TrendingTicker[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [hours, setHours] = useState(24);
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState<{ text: string; toStatus: boolean } | null>(null);

  const load = useCallback(() => {
    api.trending(hours).then(setTrending).catch(() => setTrending([]));
    api.status().then(setStatus).catch(() => setStatus(null));
  }, [hours]);

  useEffect(load, [load, refreshKey]);

  const ingestNow = async () => {
    setIngesting(true);
    setIngestError(null);
    try {
      await api.ingest();
    } catch (e) {
      // 401 (token), 403 (disabled), 429 (rate limit) carry a clear message from api.ts; strip the status prefix as Footer does.
      if (isAdminApiError(e)) setIngestError({ text: e.message.replace(/^\d{3}\s+/, ""), toStatus: e.status !== 429 });
      else setIngestError({ text: `Fetch failed. ${String(e instanceof Error ? e.message : e)}`, toStatus: false });
    } finally {
      setIngesting(false);
      load();
    }
  };

  return (
    <aside className="sidebar">
      <section className="panel">
        <div className="panel-head">
          <h2>Trending tickers</h2>
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Window">
            <option value={6}>6h</option>
            <option value={24}>24h</option>
            <option value={168}>7d</option>
          </select>
        </div>
        {trending.length === 0 ? (
          <p className="muted">No tagged tickers yet.</p>
        ) : (
          <ol className="trending">
            {trending.map((t) => (
              <li key={t.symbol}>
                <Link href={`/ticker/${t.symbol}`}>
                  <strong>{t.symbol}</strong>
                  <span className="muted ellipsis">{t.name}</span>
                </Link>
                <span className="count">{t.mentions}</span>
                <span className={`sent ${sentimentClass(t.avg_sentiment)}`}>{formatScore(t.avg_sentiment)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Sources</h2>
          <button onClick={ingestNow} disabled={ingesting} className="btn">
            {ingesting ? "Fetching…" : "Fetch now"}
          </button>
        </div>
        {ingestError && (
          <p className="error small" role="alert">
            {ingestError.text} {ingestError.toStatus && <Link href="/status">Open Status</Link>}
          </p>
        )}
        {!status ? (
          <p className="error">API unreachable. Is the backend running on :8000?</p>
        ) : (
          <>
            <p className="muted small">
              {status.articles} articles · {status.enriched} AI-enriched · {status.tickers_loaded.toLocaleString()} symbols
            </p>
            {!status.enrich_enabled && (
              <p className="hint">Set ANTHROPIC_API_KEY in .env to add AI summaries, sentiment and ticker tagging.</p>
            )}
            {!status.alpaca_enabled && (
              <p className="hint">Add Alpaca paper keys in .env for the Benzinga real-time feed.</p>
            )}
            <ul className="sources">
              {status.sources.map((s) => (
                <li key={s.name} title={s.error ?? undefined}>
                  <span className={`led ${s.error ? "bad" : s.last_run ? "ok" : ""}`} />
                  <span className="ellipsis">{s.name}</span>
                  <span className="muted small">{s.last_run ? timeAgo(s.last_run) : "pending"}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </aside>
  );
}
