"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import ArticleCard from "@/components/ArticleCard";
import DilutionPanel from "@/components/DilutionPanel";
import HaltsPanel from "@/components/HaltsPanel";
import { api, isAdminApiError, type Fundamentals, type Halt, type TickerDetail } from "@/lib/api";
import { formatMoney, formatScore, sentimentClass, SIZE_LABELS } from "@/lib/format";

import VaultNotes from "./VaultNotes";

interface Props {
  initial: TickerDetail;
  initialDays: number;
  fundamentals: Fundamentals | null;
  /** server: render with server data; client: panel fetches itself; none: section omitted */
  fundamentalsMode: "server" | "client" | "none";
  halts: Halt[] | null;
  summary: ReactNode;
  /** Server-rendered ArticleCards for `initial`; used until the window changes. */
  initialArticles: ReactNode;
  related: ReactNode;
}

/** Interactive part of /ticker/[symbol]: watch toggle, window selector, coverage chart, articles. */
export default function TickerView({ initial, initialDays, fundamentals, fundamentalsMode, halts, summary, initialArticles, related }: Props) {
  const [data, setData] = useState<TickerDetail>(initial);
  const [days, setDays] = useState(initialDays);
  const [error, setError] = useState<string | null>(null);
  const [watching, setWatching] = useState(initial.on_watchlist);
  const [watchError, setWatchError] = useState<{ text: string; toStatus: boolean } | null>(null);

  // The page is cached (ISR), so re-check the watchlist once in the browser.
  useEffect(() => {
    api
      .watchlist()
      .then((list) => setWatching(list.some((t) => t.symbol === initial.symbol)))
      .catch(() => {});
  }, [initial.symbol]);

  // The server already fetched the initialDays window, so that window is never re-fetched: compare the
  // requested window to the server one instead of a "first run" ref, which a StrictMode (dev) remount
  // resets and which would swap the server-rendered articles for a client fetch.
  useEffect(() => {
    setError(null);
    if (days === initialDays) {
      setData(initial); // back to the server data (no-op on mount)
      return;
    }
    let cancelled = false;
    api
      .ticker(initial.symbol, days)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e.message ?? e));
      });
    return () => {
      cancelled = true; // a newer window was picked before this response arrived
    };
  }, [initial, initialDays, days]);

  const toggleWatch = async () => {
    const next = !watching;
    setWatchError(null);
    try {
      await api.watch(data.symbol, next);
      setWatching(next);
    } catch (e) {
      // 401 (token), 403 (disabled), 429 (rate limit) carry a clear message from api.ts; strip the status prefix as Footer does.
      if (isAdminApiError(e)) setWatchError({ text: e.message.replace(/^\d{3}\s+/, ""), toStatus: e.status !== 429 });
      else setWatchError({ text: `Could not update the watchlist. ${String(e instanceof Error ? e.message : e)}`, toStatus: false });
    }
  };

  const maxMentions = Math.max(1, ...data.daily.map((d) => d.mentions));

  return (
    <main className="page">
      <Link href="/news" className="back">
        ← News
      </Link>
      {error && <p className="error">{error}</p>}
      <div className="ticker-head">
        <div>
          <h1>
            ${data.symbol}{" "}
            <button className={`star ${watching ? "on" : ""}`} onClick={toggleWatch} aria-pressed={watching}>
              {watching ? "★ Watching" : "☆ Watch"}
            </button>
          </h1>
          {watchError && (
            <p className="error small" role="alert">
              {watchError.text} {watchError.toStatus && <Link href="/status">Open Status</Link>}
            </p>
          )}
          <p className="muted">
            {data.name ?? "Unknown company"}
            {data.size_bucket && (
              <>
                {" · "}
                <span title={`Public float ${formatMoney(data.public_float)} as of ${data.float_as_of}`}>
                  {SIZE_LABELS[data.size_bucket]}, float {formatMoney(data.public_float)}
                </span>
              </>
            )}
            {data.cik && (
              <>
                {" · "}
                <a href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${data.cik}`} target="_blank" rel="noopener noreferrer">
                  SEC filings
                </a>
              </>
            )}
            {" · "}
            <Link href={`/graph?ticker=${encodeURIComponent(data.symbol)}`}>View in event graph</Link>
          </p>
        </div>
        <div className="stats">
          <div>
            <span className="muted small">Mentions</span>
            <strong>{data.mentions}</strong>
          </div>
          <div>
            <span className="muted small">Avg sentiment</span>
            <strong className={sentimentClass(data.avg_sentiment)}>{formatScore(data.avg_sentiment)}</strong>
          </div>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Window">
            <option value={7}>7d</option>
            <option value={30}>30d</option>
            <option value={90}>90d</option>
          </select>
        </div>
      </div>

      {summary}

      {fundamentalsMode === "server" && fundamentals && <DilutionPanel symbol={data.symbol} initialData={fundamentals} />}
      {fundamentalsMode === "client" && <DilutionPanel symbol={data.symbol} />}
      <HaltsPanel symbol={data.symbol} initialData={halts ?? undefined} />
      <VaultNotes symbol={data.symbol} />

      {data.daily.length > 0 && (
        <section className="panel">
          <h2>Coverage by day</h2>
          <div className="bars">
            {data.daily.map((d) => (
              <div key={d.day} className="bar-col" title={`${d.day}: ${d.mentions} articles, sentiment ${formatScore(d.avg_sentiment)}`}>
                <div className={`bar ${sentimentClass(d.avg_sentiment)}`} style={{ height: `${(d.mentions / maxMentions) * 100}%` }} />
                <span className="bar-label">{d.day.slice(5)}</span>
              </div>
            ))}
          </div>
          <p className="muted small">Bar height = article count. Color = average AI sentiment (grey when not scored).</p>
        </section>
      )}

      <section className="feed narrow">
        {data.articles.length === 0 && <p className="muted">No articles in this window.</p>}
        {data === initial ? initialArticles : data.articles.map((a) => <ArticleCard key={a.id} article={a} />)}
      </section>

      {related}
    </main>
  );
}
